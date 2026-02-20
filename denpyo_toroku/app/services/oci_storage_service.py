"""
OCI Object Storage サービス

Oracle Cloud Infrastructure Object Storageとの連携を管理します。
伝票ファイル（PDF/画像）のアップロード、ダウンロード、一覧取得、削除を提供します。

参考: no.1-semantic-doc-search/backend/app/services/oci_service.py
"""
import base64
import logging
import os
import random
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# レート制限対応のリトライ設定
OCI_API_MAX_RETRIES = int(os.environ.get("OCI_API_MAX_RETRIES", "5"))
OCI_API_BASE_DELAY = float(os.environ.get("OCI_API_BASE_DELAY", "1.0"))
OCI_API_MAX_DELAY = float(os.environ.get("OCI_API_MAX_DELAY", "60.0"))
OCI_API_JITTER = float(os.environ.get("OCI_API_JITTER", "0.1"))
OCI_API_CONNECT_TIMEOUT = float(os.environ.get("OCI_API_CONNECT_TIMEOUT", "10"))
OCI_API_READ_TIMEOUT = float(os.environ.get("OCI_API_READ_TIMEOUT", "30"))


class OCIStorageService:
    """OCI Object Storage サービス

    伝票ファイルのアップロード/ダウンロード/一覧取得/削除を管理します。
    レート制限対応の指数バックオフリトライ機能を内蔵しています。
    """

    def __init__(self):
        self._object_storage_client = None
        self._bucket_name = os.environ.get("OCI_BUCKET", "")
        self._namespace = os.environ.get("OCI_NAMESPACE", "")
        self._connect_timeout = OCI_API_CONNECT_TIMEOUT
        self._read_timeout = OCI_API_READ_TIMEOUT

    @property
    def is_configured(self) -> bool:
        return bool(self._bucket_name and self._namespace)

    def _get_client(self):
        """OCI Object Storage クライアントを取得（遅延初期化）"""
        if self._object_storage_client is not None:
            return self._object_storage_client

        try:
            import oci
            config_path = os.path.expanduser(
                os.environ.get("OCI_CONFIG_PATH", "~/.oci/config")
            )
            profile = os.environ.get("OCI_CONFIG_PROFILE", "DEFAULT")

            if os.path.exists(config_path):
                config = oci.config.from_file(config_path, profile)
                env_region = os.environ.get("OCI_REGION", "").strip()
                if env_region:
                    # Object Storage は .env の OCI_REGION を優先する
                    config["region"] = env_region
                self._object_storage_client = oci.object_storage.ObjectStorageClient(
                    config,
                    timeout=(self._connect_timeout, self._read_timeout),
                )
                logger.info(
                    "OCI Object Storage クライアントを初期化: region=%s ns=%s bucket=%s timeout=(%.1fs, %.1fs)",
                    config.get("region", ""),
                    self._namespace,
                    self._bucket_name,
                    self._connect_timeout,
                    self._read_timeout,
                )
            else:
                logger.warning("OCI 設定ファイルが見つかりません: %s", config_path)
                return None
        except Exception as e:
            logger.error("OCI Object Storage クライアント初期化エラー: %s", e, exc_info=True)
            return None

        return self._object_storage_client

    def _is_rate_limit_error(self, error: Exception) -> bool:
        error_str = str(error).lower()
        return (
            '429' in error_str
            or 'too many requests' in error_str
            or 'rate limit exceeded' in error_str
        )

    def _calculate_backoff_delay(self, attempt: int, is_rate_limit: bool = False) -> float:
        base_multiplier = 3.0 if is_rate_limit else 2.0
        delay = OCI_API_BASE_DELAY * (base_multiplier ** attempt)
        delay = min(delay, OCI_API_MAX_DELAY)
        jitter = random.uniform(-OCI_API_JITTER, OCI_API_JITTER) * delay
        return max(0.1, delay + jitter)

    def _is_object_not_found_error(self, error: Exception) -> bool:
        """Object Storage上にオブジェクトが存在しないエラーか判定"""
        status = getattr(error, "status", None)
        code = str(getattr(error, "code", "")).lower()
        if status == 404 and code == "objectnotfound":
            return True

        error_str = str(error).lower()
        return "objectnotfound" in error_str and "404" in error_str

    def _retry_api_call(self, operation_name: str, func, *args, **kwargs):
        """リトライ付きAPI呼び出し"""
        last_error = None
        for attempt in range(OCI_API_MAX_RETRIES):
            attempt_no = attempt + 1
            started_at = time.time()
            try:
                logger.info("%s: 試行 %d/%d 開始", operation_name, attempt_no, OCI_API_MAX_RETRIES)
                result = func(*args, **kwargs)
                elapsed = time.time() - started_at
                logger.info("%s: 試行 %d/%d 成功 (%.2fs)", operation_name, attempt_no, OCI_API_MAX_RETRIES, elapsed)
                return result
            except Exception as e:
                last_error = e
                if self._is_object_not_found_error(e):
                    logger.warning(
                        "%s: Object Storage 内で対象ファイルは既に存在しません（リトライしません）: %s",
                        operation_name,
                        str(e)[:180],
                    )
                    raise
                is_rate_limit = self._is_rate_limit_error(e)
                elapsed = time.time() - started_at
                if attempt < OCI_API_MAX_RETRIES - 1:
                    delay = self._calculate_backoff_delay(attempt, is_rate_limit)
                    logger.warning(
                        "%s: 試行 %d/%d 失敗 (%.2fs, %s: %s)。%.1f秒後にリトライ...",
                        operation_name, attempt_no, OCI_API_MAX_RETRIES, elapsed, type(e).__name__, str(e)[:180], delay
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        "%s: 試行 %d/%d 失敗 (%.2fs, %s: %s)。最大リトライ回数に到達",
                        operation_name, attempt_no, OCI_API_MAX_RETRIES, elapsed, type(e).__name__, str(e)[:180]
                    )
        raise last_error

    def upload_file(
        self,
        object_name: str,
        file_data: bytes,
        content_type: str = "application/octet-stream",
        original_filename: str = "",
    ) -> Dict[str, Any]:
        """ファイルをObject Storageにアップロード"""
        client = self._get_client()
        if not client:
            return {"success": False, "message": "OCI クライアントが初期化されていません"}

        if not self.is_configured:
            return {"success": False, "message": "OCI_BUCKET / OCI_NAMESPACE が未設定です"}

        # メタデータ（日本語ファイル名対応: ASCII ならそのまま、非ASCII は base64）
        # 参考: no.1-semantic-doc-search の OCI メタデータ方式を踏襲
        opc_meta = {
            "uploaded-at": datetime.now().isoformat(),
            "file-size": str(len(file_data)),
            "upload-source": "denpyo-toroku",
        }
        if original_filename and original_filename.strip():
            stripped = original_filename.strip()
            try:
                stripped.encode("latin-1")
                opc_meta["original-filename"] = stripped
            except UnicodeEncodeError:
                opc_meta["original-filename-b64"] = base64.b64encode(
                    stripped.encode("utf-8")
                ).decode("ascii")

        request_id = f"denpyo-upload-{int(time.time() * 1000)}"
        started_at = time.time()
        logger.info(
            "upload_file 開始: request_id=%s object=%s size=%d content_type=%s ns=%s bucket=%s",
            request_id, object_name, len(file_data), content_type, self._namespace, self._bucket_name
        )
        try:
            self._retry_api_call(
                "upload_file",
                client.put_object,
                namespace_name=self._namespace,
                bucket_name=self._bucket_name,
                object_name=object_name,
                put_object_body=file_data,
                content_type=content_type,
                opc_meta=opc_meta,
                opc_client_request_id=request_id,
            )
            elapsed = time.time() - started_at
            logger.info("upload_file 完了: request_id=%s object=%s elapsed=%.2fs", request_id, object_name, elapsed)
            return {
                "success": True,
                "message": "アップロード完了",
                "object_name": object_name,
                "size": len(file_data),
            }
        except Exception as e:
            elapsed = time.time() - started_at
            logger.error(
                "upload_file 失敗: request_id=%s object=%s elapsed=%.2fs err=%s",
                request_id, object_name, elapsed, e, exc_info=True
            )
            return {"success": False, "message": f"アップロード失敗: {str(e)}"}

    def download_file(self, object_name: str) -> Optional[bytes]:
        """ファイルをObject Storageからダウンロード"""
        client = self._get_client()
        if not client or not self.is_configured:
            return None

        try:
            response = self._retry_api_call(
                "download_file",
                client.get_object,
                namespace_name=self._namespace,
                bucket_name=self._bucket_name,
                object_name=object_name,
            )
            return response.data.content
        except Exception as e:
            logger.error("ファイルダウンロードエラー: %s", e, exc_info=True)
            return None

    def list_files(self, prefix: str = "") -> List[Dict[str, Any]]:
        """Object Storage内のファイル一覧を取得"""
        client = self._get_client()
        if not client or not self.is_configured:
            return []

        try:
            kwargs = {
                "namespace_name": self._namespace,
                "bucket_name": self._bucket_name,
                "fields": "name,size,timeCreated,md5",
            }
            if prefix:
                kwargs["prefix"] = prefix

            response = self._retry_api_call(
                "list_files",
                client.list_objects,
                **kwargs,
            )

            files = []
            for obj in response.data.objects:
                files.append({
                    "name": obj.name,
                    "size": getattr(obj, "size", 0),
                    "time_created": str(getattr(obj, "time_created", "")),
                    "md5": getattr(obj, "md5", ""),
                })
            return files
        except Exception as e:
            logger.error("ファイル一覧取得エラー: %s", e, exc_info=True)
            return []

    def delete_file(self, object_name: str) -> Dict[str, Any]:
        """Object Storageからファイルを削除"""
        logger.info("[OCI Storage] delete_file 開始: object_name=%s", object_name)
        client = self._get_client()
        if not client:
            logger.error("[OCI Storage] client が None です")
            return {"success": False, "message": "OCI クライアントが利用できません"}
        if not self.is_configured:
            logger.error("[OCI Storage] is_configured=False (namespace=%s, bucket=%s)",
                        self._namespace, self._bucket_name)
            return {"success": False, "message": "OCI クライアントが利用できません"}

        try:
            logger.info("[OCI Storage] API呼び出し中: delete_object(namespace=%s, bucket=%s, object=%s)",
                       self._namespace, self._bucket_name, object_name)
            self._retry_api_call(
                "delete_file",
                client.delete_object,
                namespace_name=self._namespace,
                bucket_name=self._bucket_name,
                object_name=object_name,
            )
            logger.info("✅ [OCI Storage] ファイルを削除しました: %s", object_name)
            return {"success": True, "message": "削除完了", "object_name": object_name}
        except Exception as e:
            if self._is_object_not_found_error(e):
                logger.warning(
                    "⚠️ [OCI Storage] 削除対象は既に存在しません: %s (%s)",
                    object_name,
                    e,
                )
                return {
                    "success": True,
                    "already_missing": True,
                    "message": "Object Storage 内でファイルは既に存在しません",
                    "object_name": object_name,
                }
            logger.error("❌ [OCI Storage] ファイル削除エラー: %s", e, exc_info=True)
            return {"success": False, "message": f"削除失敗: {str(e)}"}

    def get_file_metadata(self, object_name: str) -> Optional[Dict[str, Any]]:
        """ファイルのメタデータを取得"""
        client = self._get_client()
        if not client or not self.is_configured:
            return None

        try:
            response = self._retry_api_call(
                "get_file_metadata",
                client.head_object,
                namespace_name=self._namespace,
                bucket_name=self._bucket_name,
                object_name=object_name,
            )
            headers = response.headers
            opc_meta = {
                k.replace("opc-meta-", ""): v
                for k, v in headers.items()
                if k.startswith("opc-meta-")
            }

            # 元ファイル名を復元（base64 → plain → オブジェクト名のフォールバック）
            # 参考: no.1-semantic-doc-search の復元ロジックを踏襲
            original_filename = ""
            if "original-filename-b64" in opc_meta:
                try:
                    original_filename = base64.b64decode(
                        opc_meta["original-filename-b64"]
                    ).decode("utf-8")
                except Exception:
                    pass
            if not original_filename:
                original_filename = opc_meta.get(
                    "original-filename", object_name.rsplit("/", 1)[-1]
                )

            return {
                "object_name": object_name,
                "content_type": headers.get("content-type", ""),
                "content_length": int(headers.get("content-length", 0)),
                "etag": headers.get("etag", ""),
                "last_modified": headers.get("last-modified", ""),
                "original_filename": original_filename,
                "metadata": opc_meta,
            }
        except Exception as e:
            logger.error("メタデータ取得エラー: %s", e, exc_info=True)
            return None
