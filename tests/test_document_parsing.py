from __future__ import annotations

import io
import zipfile

import pytest

from app.services.document_parsing import (
    UnsupportedDocumentTypeError,
    extract_csv_text,
    extract_docx_text,
    extract_pdf_text,
    extract_text_from_document,
    extract_xlsx_text,
)


def test_extract_plain_text_document() -> None:
    assert extract_text_from_document(b"Hello Rhapsody", "note.txt") == "Hello Rhapsody"


def test_extract_csv_text_formats_rows() -> None:
    assert extract_csv_text(b"name,status\nTask A,open") == "name | status\nTask A | open"


def test_extract_docx_text_from_minimal_archive() -> None:
    content = build_zip(
        {
            "word/document.xml": """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body><w:p><w:r><w:t>Hello</w:t></w:r><w:r><w:t> docx</w:t></w:r></w:p></w:body>
            </w:document>
            """,
        }
    )

    assert extract_docx_text(content) == "Hello docx"


def test_extract_xlsx_text_from_minimal_archive() -> None:
    content = build_zip(
        {
            "xl/sharedStrings.xml": """
            <sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
              <si><t>Task</t></si><si><t>Done</t></si>
            </sst>
            """,
            "xl/worksheets/sheet1.xml": """
            <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
              <sheetData><row><c t="s"><v>0</v></c><c t="s"><v>1</v></c></row></sheetData>
            </worksheet>
            """,
        }
    )

    assert extract_xlsx_text(content) == "Task | Done"


def test_extract_pdf_text_from_simple_text_operator() -> None:
    assert extract_pdf_text(b"BT (Hello PDF) Tj ET") == "Hello PDF"


def test_unsupported_document_type_raises_safe_error() -> None:
    with pytest.raises(UnsupportedDocumentTypeError):
        extract_text_from_document(b"binary", "archive.zip")


def build_zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()