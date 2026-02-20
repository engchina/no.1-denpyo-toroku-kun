"""
ドキュメントプロセッサ

伝票ファイル（PDF/画像）の前処理を行います。
- PDFからの画像変換
- 画像のリサイズ・最適化
- MIMEタイプの判定
- ファイルバリデーション

参考: no.1-semantic-doc-search/backend/app/services/document_processor.py
"""
import io
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 対応ファイル形式
ALLOWED_EXTENSION_LIST = ("pdf", "jpeg", "jpg", "png", "tif", "tiff")
ALLOWED_EXTENSIONS = set(ALLOWED_EXTENSION_LIST)
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/tiff",
    "image/tif",
}

# デフォルト最大サイズ（MB）
DEFAULT_MAX_SIZE_MB = 50


class DocumentProcessor:
    """ドキュメントプロセッサ

    アップロードされた伝票ファイルのバリデーションと前処理を行います。
    PDFの場合は画像に変換してAI分析に渡せる形式にします。
    """

    def __init__(self, max_size_mb: int = DEFAULT_MAX_SIZE_MB):
        self._max_size_bytes = max_size_mb * 1024 * 1024

    def validate_file(self, filename: str, file_data: bytes, content_type: str = "") -> Dict[str, Any]:
        """ファイルのバリデーション"""
        if not filename:
            return {"valid": False, "message": "ファイル名が空です"}

        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in ALLOWED_EXTENSIONS:
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

        return {"valid": True, "extension": ext, "size": len(file_data)}

    def detect_content_type(self, filename: str, file_data: bytes = b"") -> str:
        """ファイル名とマジックバイトからコンテンツタイプを判定"""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

        # マジックバイトによる判定
        if file_data:
            if file_data[:4] == b'%PDF':
                return "application/pdf"
            if file_data[:2] == b'\xff\xd8':
                return "image/jpeg"
            if file_data[:8] == b'\x89PNG\r\n\x1a\n':
                return "image/png"
            if file_data[:4] in (b'II*\x00', b'MM\x00*'):
                return "image/tiff"

        # 拡張子による判定
        ext_map = {
            "pdf": "application/pdf",
            "jpeg": "image/jpeg",
            "jpg": "image/jpeg",
            "png": "image/png",
            "tif": "image/tiff",
            "tiff": "image/tiff",
        }
        return ext_map.get(ext, "application/octet-stream")

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

    def prepare_for_ai(self, file_data: bytes, filename: str) -> List[Tuple[bytes, str]]:
        """ファイルをAI分析用に準備する

        Returns:
            List of (image_data, content_type) tuples
        """
        content_type = self.detect_content_type(filename, file_data)

        if content_type == "application/pdf":
            page_images = self.pdf_to_images(file_data)
            if not page_images:
                logger.warning("PDF変換で画像が生成されませんでした: %s", filename)
                return []
            return [(img, "image/jpeg") for img in page_images]

        # 画像ファイルの場合はそのまま返す
        return [(file_data, content_type)]

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
