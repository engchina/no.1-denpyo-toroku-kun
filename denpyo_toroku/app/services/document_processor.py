"""
ドキュメントプロセッサ

伝票ファイル（PDF/画像/ZIP）の前処理を行います。
- PDFからの画像変換
- ZIP内容の事前検証
- 画像のリサイズ・最適化
- MIMEタイプの判定
- ファイルバリデーション

参考: no.1-semantic-doc-search/backend/app/services/document_processor.py
"""
import io
import logging
import os
import shutil
import stat
import tempfile
import zipfile
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 対応ファイル形式
ALLOWED_EXTENSION_LIST = ("pdf", "jpeg", "jpg", "png", "tif", "tiff", "zip")
ALLOWED_EXTENSIONS = set(ALLOWED_EXTENSION_LIST)
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/zip",
    "application/x-zip-compressed",
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/tiff",
    "image/tif",
}
ZIP_ALLOWED_EXTENSION_LIST = ("jpeg", "jpg", "png", "tif", "tiff")
ZIP_ALLOWED_EXTENSIONS = set(ZIP_ALLOWED_EXTENSION_LIST)
ZIP_ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/tiff",
}

# デフォルト最大サイズ（MB）
DEFAULT_MAX_SIZE_MB = 50


class DocumentProcessor:
    """ドキュメントプロセッサ

    アップロードされた伝票ファイルのバリデーションと前処理を行います。
    PDF は画像に変換し、ZIP はアップロード前の内容検証のみ行います。
    """

    def __init__(self, max_size_mb: int = DEFAULT_MAX_SIZE_MB):
        self._max_size_bytes = max_size_mb * 1024 * 1024

    def validate_file(self, filename: str, file_data: bytes, content_type: str = "") -> Dict[str, Any]:
        """ファイルのバリデーション"""
        if not filename:
            return {"valid": False, "message": "ファイル名が空です"}

        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        is_zip = ext == "zip" or self.is_zip_archive(filename, file_data)

        if ext not in ALLOWED_EXTENSIONS and not is_zip:
            return {
                "valid": False,
                "message": f"対応していないファイル形式です: .{ext} (対応: {', '.join(ALLOWED_EXTENSION_LIST)})"
            }

        if len(file_data) > self._max_size_bytes:
            size_mb = len(file_data) / (1024 * 1024)
            return {
                "valid": False,
                "message": f"ファイルサイズが上限を超えています: {size_mb:.1f}MB (上限: {self._max_size_bytes / (1024 * 1024):.0f}MB)"
            }

        if len(file_data) == 0:
            return {"valid": False, "message": "ファイルが空です"}

        if is_zip:
            zip_result = self.extract_zip_image_entries(filename, file_data)
            if not zip_result.get("valid"):
                return {"valid": False, "message": zip_result.get("message", "ZIPファイルの処理に失敗しました")}
            return {
                "valid": True,
                "extension": "zip",
                "size": len(file_data),
                "entry_count": len(zip_result.get("files", [])),
            }

        return {"valid": True, "extension": ext, "size": len(file_data)}

    def detect_content_type_by_magic(self, file_data: bytes) -> str:
        """マジックバイトだけでコンテンツタイプを判定"""
        if not file_data:
            return ""
        if file_data[:4] == b"%PDF":
            return "application/pdf"
        if file_data[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
            return "application/zip"
        if file_data[:2] == b"\xff\xd8":
            return "image/jpeg"
        if file_data[:8] == b"\x89PNG\r\n\x1a\n":
            return "image/png"
        if file_data[:4] in (b"II*\x00", b"MM\x00*"):
            return "image/tiff"
        return ""

    def detect_content_type(self, filename: str, file_data: bytes = b"") -> str:
        """ファイル名とマジックバイトからコンテンツタイプを判定"""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

        # マジックバイトによる判定
        detected_by_magic = self.detect_content_type_by_magic(file_data)
        if detected_by_magic:
            return detected_by_magic

        # 拡張子による判定
        ext_map = {
            "pdf": "application/pdf",
            "zip": "application/zip",
            "jpeg": "image/jpeg",
            "jpg": "image/jpeg",
            "png": "image/png",
            "tif": "image/tiff",
            "tiff": "image/tiff",
        }
        return ext_map.get(ext, "application/octet-stream")

    def is_zip_archive(self, filename: str, file_data: bytes) -> bool:
        """ZIPアーカイブかどうかを判定"""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext == "zip":
            return True
        if not file_data:
            return False
        try:
            return zipfile.is_zipfile(io.BytesIO(file_data))
        except Exception:
            return False

    def extract_zip_image_entries(
        self,
        filename: str,
        file_data: bytes,
        include_file_data: bool = False,
    ) -> Dict[str, Any]:
        """ZIP を一時展開し、JPEG/PNG/TIFF のみを抽出する"""
        if not filename:
            return {"valid": False, "message": "ファイル名が空です", "files": []}

        if len(file_data) > self._max_size_bytes:
            size_mb = len(file_data) / (1024 * 1024)
            return {
                "valid": False,
                "message": f"ZIPファイルサイズが上限を超えています: {size_mb:.1f}MB (上限: {self._max_size_bytes / (1024 * 1024):.0f}MB)",
                "files": [],
            }

        if len(file_data) == 0:
            return {"valid": False, "message": "ZIPファイルが空です", "files": []}

        if not self.is_zip_archive(filename, file_data):
            return {"valid": False, "message": "有効なZIPファイルではありません", "files": []}

        archive_name = os.path.basename(filename) or filename

        try:
            with zipfile.ZipFile(io.BytesIO(file_data)) as zip_ref:
                file_infos = [info for info in zip_ref.infolist() if not info.is_dir()]
                if not file_infos:
                    return {"valid": False, "message": "ZIP内にファイルが存在しません", "files": []}

                extracted_files = []
                with tempfile.TemporaryDirectory(prefix="denpyo_zip_") as temp_dir:
                    for info in file_infos:
                        normalized_entry_name = self._normalize_zip_entry_name(info.filename)
                        if not normalized_entry_name:
                            continue

                        if self._is_zip_symlink(info):
                            return {
                                "valid": False,
                                "message": f"ZIP内にシンボリックリンクが含まれています: {normalized_entry_name}",
                                "files": [],
                            }

                        target_path = os.path.join(temp_dir, *normalized_entry_name.split("/"))
                        os.makedirs(os.path.dirname(target_path), exist_ok=True)

                        with zip_ref.open(info, "r") as src, open(target_path, "wb") as dst:
                            shutil.copyfileobj(src, dst)

                        with open(target_path, "rb") as extracted_file:
                            extracted_data = extracted_file.read()

                        entry_ext = normalized_entry_name.rsplit(".", 1)[-1].lower() if "." in normalized_entry_name else ""
                        if entry_ext not in ZIP_ALLOWED_EXTENSIONS:
                            return {
                                "valid": False,
                                "message": (
                                    f"ZIP内に対応外のファイル形式が含まれています: {normalized_entry_name} "
                                    "(対応: JPEG, PNG, TIFF)"
                                ),
                                "files": [],
                            }

                        validation = self.validate_file(normalized_entry_name, extracted_data)
                        if not validation.get("valid"):
                            return {
                                "valid": False,
                                "message": f"ZIP内ファイルの検証に失敗しました: {normalized_entry_name} ({validation.get('message', '無効なファイル')})",
                                "files": [],
                            }

                        content_type = self.detect_content_type_by_magic(extracted_data)
                        if content_type not in ZIP_ALLOWED_CONTENT_TYPES:
                            return {
                                "valid": False,
                                "message": (
                                    f"ZIP内に対応外のファイル形式が含まれています: {normalized_entry_name} "
                                    "(対応: JPEG, PNG, TIFF)"
                                ),
                                "files": [],
                            }

                        extracted_files.append({
                            "archive_filename": archive_name,
                            "entry_name": normalized_entry_name,
                            "content_type": content_type,
                            "size": len(extracted_data),
                            "file_data": extracted_data if include_file_data else b"",
                        })

                if not extracted_files:
                    return {"valid": False, "message": "ZIP内に有効な画像ファイルがありません", "files": []}

                return {"valid": True, "files": extracted_files}
        except ValueError:
            raise
        except zipfile.BadZipFile:
            return {"valid": False, "message": "ZIPファイルの読み込みに失敗しました", "files": []}
        except RuntimeError as e:
            logger.warning("ZIP展開エラー: %s", e)
            return {"valid": False, "message": f"ZIPファイルの展開に失敗しました: {e}", "files": []}
        except Exception as e:
            logger.error("ZIP画像抽出エラー: %s", e, exc_info=True)
            return {"valid": False, "message": f"ZIPファイルの処理に失敗しました: {e}", "files": []}

    @staticmethod
    def _normalize_zip_entry_name(entry_name: str) -> str:
        normalized = str(entry_name or "").replace("\\", "/").strip()
        if not normalized:
            raise ValueError("ZIP内に名前が空のエントリが含まれています")

        path = PurePosixPath(normalized)
        parts = [part for part in path.parts if part not in ("", ".")]
        if path.is_absolute() or ".." in parts:
            raise ValueError(f"ZIP内に不正なパスが含まれています: {entry_name}")
        return "/".join(parts)

    @staticmethod
    def _is_zip_symlink(info: zipfile.ZipInfo) -> bool:
        mode = info.external_attr >> 16
        return stat.S_ISLNK(mode)

    def is_pdf(self, file_data: bytes) -> bool:
        """PDFファイルかどうかを判定"""
        return file_data[:4] == b'%PDF'

    def pdf_to_images(self, pdf_data: bytes, dpi: int = 200) -> List[bytes]:
        """PDFを画像（JPEG）のリストに変換

        pdf2image (poppler) が利用可能な場合はそれを使用し、
        利用できない場合はPyMuPDF (fitz) にフォールバックします。
        """
        images = []

        # pdf2image を試行
        try:
            from pdf2image import convert_from_bytes
            pil_images = convert_from_bytes(pdf_data, dpi=dpi)
            for pil_img in pil_images:
                buf = io.BytesIO()
                pil_img.save(buf, format="JPEG", quality=90)
                images.append(buf.getvalue())
            logger.info("PDF → 画像変換完了 (pdf2image): %dページ", len(images))
            return images
        except ImportError:
            logger.info("pdf2image が利用できません。PyMuPDF を試みます...")
        except Exception as e:
            logger.warning("pdf2image でのPDF変換エラー: %s", e)

        # PyMuPDF (fitz) にフォールバック
        try:
            import fitz
            doc = fitz.open(stream=pdf_data, filetype="pdf")
            for page in doc:
                # ピクセルマップを取得（DPI相当のズーム）
                zoom = dpi / 72.0
                matrix = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=matrix)
                img_data = pix.tobytes("jpeg")
                images.append(img_data)
            doc.close()
            logger.info("PDF → 画像変換完了 (PyMuPDF): %dページ", len(images))
            return images
        except ImportError:
            logger.error("PyMuPDF (fitz) も利用できません。PDF変換にはpdf2imageまたはPyMuPDFが必要です。")
        except Exception as e:
            logger.error("PyMuPDF でのPDF変換エラー: %s", e, exc_info=True)

        return images

    def prepare_document_pages(self, file_data: bytes, filename: str) -> List[Dict[str, Any]]:
        """ファイルをページ画像列に変換する"""
        content_type = self.detect_content_type(filename, file_data)

        if content_type == "application/pdf":
            page_images = self.pdf_to_images(file_data)
            if not page_images:
                logger.warning("PDF変換で画像が生成されませんでした: %s", filename)
                return []
            return [
                {
                    "image_data": img,
                    "content_type": "image/jpeg",
                    "page_index": index,
                    "page_label": f"ページ {index + 1}",
                    "source_name": f"{filename}#page-{index + 1}",
                }
                for index, img in enumerate(page_images)
            ]

        if self.is_zip_archive(filename, file_data):
            zip_result = self.extract_zip_image_entries(
                filename,
                file_data,
                include_file_data=True,
            )
            if not zip_result.get("valid"):
                logger.warning("ZIP展開で画像が生成されませんでした: %s (%s)", filename, zip_result.get("message", ""))
                return []

            prepared_pages: List[Dict[str, Any]] = []
            for index, entry in enumerate(zip_result.get("files", [])):
                entry_name = str(entry.get("entry_name") or entry.get("filename") or f"image-{index + 1}")
                prepared_pages.append({
                    "image_data": entry.get("file_data", b""),
                    "content_type": entry.get("content_type", "image/jpeg"),
                    "page_index": index,
                    "page_label": entry_name,
                    "source_name": entry_name,
                })
            return prepared_pages

        return [{
            "image_data": file_data,
            "content_type": content_type,
            "page_index": 0,
            "page_label": "画像 1",
            "source_name": filename,
        }]

    def prepare_for_ai(self, file_data: bytes, filename: str) -> List[Tuple[bytes, str]]:
        """ファイルをAI分析用に準備する

        Returns:
            List of (image_data, content_type) tuples
        """
        return [
            (page["image_data"], page["content_type"])
            for page in self.prepare_document_pages(file_data, filename)
            if page.get("image_data")
        ]

    def generate_object_name(self, original_filename: str, prefix: str = "denpyo") -> str:
        """Object Storage用のオブジェクト名を生成

        命名規則: {prefix}/{YYYYMMDD_HHMMSS}_{uuid[:8]}_{sanitized_original_filename}
        - タイムスタンプで時系列ソート可能
        - UUID接頭辞で衝突防止
        - サニタイズ済み元ファイル名で人間が識別可能

        参考: no.1-semantic-doc-search の命名規則を踏襲
        """
        import re
        import uuid
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        short_uuid = str(uuid.uuid4())[:8]

        # 危険な文字をアンダースコアに置換（パストラバーサル対策含む）
        safe_basename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", original_filename)
        safe_basename = safe_basename.replace("..", "_")
        if not safe_basename or safe_basename.strip() == "":
            safe_basename = "unnamed_file"

        safe_filename = f"{timestamp}_{short_uuid}_{safe_basename}"
        return f"{prefix}/{safe_filename}"
