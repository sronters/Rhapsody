from __future__ import annotations

import csv
import io
import re
import zipfile
from html import unescape
from pathlib import Path
from xml.etree import ElementTree


class UnsupportedDocumentTypeError(ValueError):
    pass


TEXT_CONTENT_TYPES = {
    "text/plain",
    "text/markdown",
    "application/json",
}


def extract_text_from_document(
    content: bytes,
    filename: str,
    content_type: str | None = None,
) -> str:
    extension = Path(filename).suffix.lower()
    normalized_type = (content_type or "").split(";", maxsplit=1)[0].strip().lower()

    if normalized_type == "text/csv" or extension == ".csv":
        return extract_csv_text(content)
    if normalized_type in TEXT_CONTENT_TYPES or extension in {".txt", ".md", ".markdown", ".json"}:
        return decode_text(content)
    if extension == ".docx" or normalized_type.endswith("wordprocessingml.document"):
        return extract_docx_text(content)
    if extension == ".xlsx" or normalized_type.endswith("spreadsheetml.sheet"):
        return extract_xlsx_text(content)
    if extension == ".pdf" or normalized_type == "application/pdf":
        return extract_pdf_text(content)
    raise UnsupportedDocumentTypeError(f"Unsupported document type: {content_type or extension}")


def decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1251", "latin-1"):
        try:
            return content.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace").strip()


def extract_csv_text(content: bytes) -> str:
    text = decode_text(content)
    rows = csv.reader(io.StringIO(text))
    formatted_rows = (" | ".join(cell.strip() for cell in row if cell.strip()) for row in rows)
    return "\n".join(formatted_rows).strip()


def extract_docx_text(content: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        document_xml = archive.read("word/document.xml")
    root = ElementTree.fromstring(document_xml)  # noqa: S314 - OOXML from trusted worker input.
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs: list[str] = []
    for paragraph in root.iter(f"{namespace}p"):
        parts = [node.text or "" for node in paragraph.iter(f"{namespace}t")]
        paragraph_text = "".join(parts).strip()
        if paragraph_text:
            paragraphs.append(paragraph_text)
    return "\n".join(paragraphs)


def extract_xlsx_text(content: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        shared_strings = read_xlsx_shared_strings(archive)
        sheet_names = sorted(
            name for name in archive.namelist() if name.startswith("xl/worksheets/sheet")
        )
        rows: list[str] = []
        for sheet_name in sheet_names:
            root = ElementTree.fromstring(  # noqa: S314 - OOXML from trusted worker input.
                archive.read(sheet_name)
            )
            rows.extend(extract_xlsx_rows(root, shared_strings))
    return "\n".join(row for row in rows if row).strip()


def read_xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ElementTree.fromstring(  # noqa: S314 - OOXML from trusted worker input.
        archive.read("xl/sharedStrings.xml")
    )
    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    strings: list[str] = []
    for item in root.iter(f"{namespace}si"):
        strings.append("".join(node.text or "" for node in item.iter(f"{namespace}t")))
    return strings


def extract_xlsx_rows(root: ElementTree.Element, shared_strings: list[str]) -> list[str]:
    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    rows: list[str] = []
    for row in root.iter(f"{namespace}row"):
        values: list[str] = []
        for cell in row.iter(f"{namespace}c"):
            value = cell.find(f"{namespace}v")
            if value is None or value.text is None:
                continue
            if cell.attrib.get("t") == "s":
                index = int(value.text)
                values.append(shared_strings[index] if index < len(shared_strings) else "")
            else:
                values.append(value.text)
        rows.append(" | ".join(item for item in values if item))
    return rows


def extract_pdf_text(content: bytes) -> str:
    # Minimal dependency-free extraction for text-heavy PDFs. Production can replace this with
    # pypdf/pdfminer in the worker while keeping the same service boundary.
    decoded = content.decode("latin-1", errors="ignore")
    literal_strings = re.findall(r"\(([^()]*)\)\s*Tj", decoded)
    array_strings = re.findall(r"\[((?:\([^()]*\)\s*)+)\]\s*TJ", decoded)
    parts = [unescape_pdf_text(item) for item in literal_strings]
    for array in array_strings:
        parts.extend(unescape_pdf_text(item) for item in re.findall(r"\(([^()]*)\)", array))
    text = " ".join(part.strip() for part in parts if part.strip())
    return unescape(text).strip()


def unescape_pdf_text(value: str) -> str:
    return (
        value.replace(r"\(", "(")
        .replace(r"\)", ")")
        .replace(r"\n", "\n")
        .replace(r"\r", "")
        .replace(r"\t", "\t")
    )
