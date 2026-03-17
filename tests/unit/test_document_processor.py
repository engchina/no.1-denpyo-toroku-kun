import base64
from io import BytesIO
import zipfile

from denpyo_toroku.app.services.document_processor import DocumentProcessor


PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a6d8AAAAASUVORK5CYII="
)


def _build_zip_file(entries):
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for name, data in entries.items():
            zip_file.writestr(name, data)
    zip_buffer.seek(0)
    return zip_buffer.getvalue()


def test_extract_zip_image_entries_includes_image_bytes_when_requested():
    processor = DocumentProcessor()
    zip_bytes = _build_zip_file({
        "invoice-1.png": PNG_BYTES,
        "nested/invoice-2.png": PNG_BYTES,
    })

    result = processor.extract_zip_image_entries("batch.zip", zip_bytes, include_file_data=True)

    assert result["valid"] is True
    assert len(result["files"]) == 2
    assert result["files"][0]["entry_name"] == "invoice-1.png"
    assert result["files"][0]["file_data"] == PNG_BYTES
    assert result["files"][1]["entry_name"] == "nested/invoice-2.png"
    assert result["files"][1]["file_data"] == PNG_BYTES


def test_prepare_document_pages_and_prepare_for_ai_return_zip_images():
    processor = DocumentProcessor()
    zip_bytes = _build_zip_file({
        "invoice-1.png": PNG_BYTES,
        "nested/invoice-2.png": PNG_BYTES,
    })

    pages = processor.prepare_document_pages(zip_bytes, "batch.zip")
    ai_images = processor.prepare_for_ai(zip_bytes, "batch.zip")

    assert len(pages) == 2
    assert pages[0]["source_name"] == "invoice-1.png"
    assert pages[0]["content_type"] == "image/png"
    assert pages[0]["image_data"] == PNG_BYTES
    assert pages[1]["source_name"] == "nested/invoice-2.png"
    assert pages[1]["image_data"] == PNG_BYTES
    assert ai_images == [
        (PNG_BYTES, "image/png"),
        (PNG_BYTES, "image/png"),
    ]
