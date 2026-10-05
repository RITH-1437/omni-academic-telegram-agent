import csv
import html
import io
import json
import logging
import re
import xml.etree.ElementTree as ET
import zipfile
from typing import Any, Dict, List, Optional, Tuple

import docx
import pypdf
import pptx

try:
    import openpyxl
except ImportError:
    openpyxl = None

logger = logging.getLogger(__name__)

# Max characters of extracted text passed to LLM (approx 20,000-25,000 tokens)
MAX_EXTRACTED_CHARS = 80000
# Max uncompressed size of an OpenDocument content.xml (guards against zip bombs)
MAX_ODF_CONTENT_BYTES = 50 * 1024 * 1024

# Formats that are never text: media, archives, executables, fonts, databases, model weights
BINARY_EXTENSIONS = {
    "jpg", "jpeg", "png", "gif", "bmp", "webp", "tiff", "tif", "ico", "heic", "psd",
    "mp3", "wav", "ogg", "oga", "flac", "m4a", "aac", "opus",
    "mp4", "mkv", "mov", "avi", "webm", "flv", "wmv", "3gp",
    "zip", "rar", "7z", "tar", "gz", "tgz", "bz2", "xz", "iso", "dmg",
    "exe", "msi", "dll", "so", "bin", "apk", "aab", "ipa", "deb", "rpm", "jar", "class", "pyc",
    "ttf", "otf", "woff", "woff2", "db", "sqlite", "pkl", "npy", "npz", "h5", "pt", "onnx",
}
BINARY_MIME_PREFIXES = ("image/", "audio/", "video/", "font/")


class DocumentParseError(Exception):
    """Custom exception raised when a document cannot be read or parsed."""
    pass


class DocumentParser:
    """
    Comprehensive In-Memory Document & Data Extractor.
    Supports:
    - Office: PDF (.pdf), Word (.docx, .doc), PowerPoint (.pptx, .ppt), Excel (.xlsx, .xls)
    - OpenDocument: .odt, .ods, .odp
    - Notebooks: Jupyter Notebook (.ipynb)
    - Tabular: CSV (.csv), TSV (.tsv)
    - Web / Markup: HTML (.html, .htm), XML (.xml), SVG (.svg)
    - Config & Data: JSON (.json), YAML (.yaml, .yml), TOML (.toml), INI (.ini)
    - Academic: LaTeX (.tex)
    - Code: Python, C/C++, Java, C#, Go, Rust, TypeScript, JavaScript, SQL, Shell, etc.
    """

    SUPPORTED_EXTENSIONS = {
        # PDF & Office
        "pdf", "docx", "doc", "pptx", "ppt", "xlsx", "xls",
        # OpenDocument
        "odt", "ods", "odp", "rtf",
        # Data & Notebooks
        "ipynb", "csv", "tsv", "json", "yaml", "yml", "toml", "xml", "html", "htm", "svg", "ini", "env",
        # Academic & Text
        "txt", "md", "tex", "log",
        # Source Code
        "py", "java", "cpp", "c", "h", "hpp", "cs", "go", "rs", "ts", "js",
        "tsx", "jsx", "sql", "sh", "bash", "ps1", "r", "kt", "dart", "php", "swift",
    }

    @staticmethod
    def is_supported_upload(filename: str, mime_type: Optional[str] = None) -> bool:
        """Cheap pre-download check that rules out media, archives, and executables."""
        ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        if ext in DocumentParser.SUPPORTED_EXTENSIONS:
            return True
        if ext in BINARY_EXTENSIONS:
            return False
        if mime_type and mime_type.lower().startswith(BINARY_MIME_PREFIXES):
            return False
        # Unknown extension (Makefile, Dockerfile, .kt, ...): content is sniffed after download
        return True

    @staticmethod
    def extract_text(file_bytes: bytes, filename: str) -> Tuple[str, dict]:
        """
        Extract text from file bytes without writing to disk.
        Returns:
            Tuple[extracted_text: str, metadata: dict]
        """
        ext = filename.lower().split(".")[-1]
        stream = io.BytesIO(file_bytes)

        # 1. PDF
        if ext == "pdf":
            return DocumentParser._parse_pdf(stream, filename)

        # 2. Word (.docx, .doc)
        elif ext in ("docx", "doc"):
            return DocumentParser._parse_docx(stream, filename)

        # 3. PowerPoint (.pptx, .ppt)
        elif ext in ("pptx", "ppt"):
            return DocumentParser._parse_pptx(stream, filename)

        # 4. Excel (.xlsx, .xls)
        elif ext in ("xlsx", "xls"):
            return DocumentParser._parse_excel(stream, filename)

        # 5. Jupyter Notebook (.ipynb)
        elif ext == "ipynb":
            return DocumentParser._parse_jupyter(stream, filename)

        # 6. Tabular (CSV, TSV)
        elif ext in ("csv", "tsv"):
            return DocumentParser._parse_csv(stream, filename, ext)

        # 7. OpenDocument (.odt, .ods, .odp)
        elif ext in ("odt", "ods", "odp"):
            return DocumentParser._parse_opendocument(stream, filename, ext)

        # 8. Rich Text (.rtf)
        elif ext == "rtf":
            return DocumentParser._parse_rtf(stream, filename)

        # 9. HTML / XML
        elif ext in ("html", "htm", "xml", "svg"):
            return DocumentParser._parse_markup(stream, filename)

        # 10. Source Code & General Text (unknown extensions only if the bytes look like text)
        elif ext in DocumentParser.SUPPORTED_EXTENSIONS or (
            ext not in BINARY_EXTENSIONS and DocumentParser._looks_like_text(file_bytes)
        ):
            return DocumentParser._parse_text(stream, filename)

        else:
            raise DocumentParseError(
                f"Unsupported file format '.{ext}'. Supported formats: .pdf, .docx, .pptx, .xlsx, .ipynb, .csv, and code/text files."
            )

    # --------------------------------------------------------------------------
    # 1. PDF Parser
    # --------------------------------------------------------------------------

    @staticmethod
    def _parse_pdf(stream: io.BytesIO, filename: str) -> Tuple[str, dict]:
        try:
            reader = pypdf.PdfReader(stream)
            total_pages = len(reader.pages)
            extracted_pages = []

            for i, page in enumerate(reader.pages):
                page_text = page.extract_text() or ""
                cleaned = page_text.strip()
                if cleaned:
                    extracted_pages.append(f"--- [Page {i + 1}] ---\n{cleaned}")

            full_text = "\n\n".join(extracted_pages)
            if not full_text.strip():
                raise DocumentParseError(
                    "The PDF appears to be empty or contains only scanned images without extractable text."
                )

            metadata = {"type": "PDF", "total_pages": total_pages, "filename": filename}
            return DocumentParser._sanitize_length(full_text, metadata)

        except Exception as e:
            if isinstance(e, DocumentParseError):
                raise
            logger.error("Failed to parse PDF %s: %s", filename, e, exc_info=True)
            raise DocumentParseError(f"Error reading PDF document: {e}")

    # --------------------------------------------------------------------------
    # 2. Word Parser (.docx, .doc)
    # --------------------------------------------------------------------------

    @staticmethod
    def _parse_docx(stream: io.BytesIO, filename: str) -> Tuple[str, dict]:
        try:
            doc = docx.Document(stream)
            content = []

            # Paragraphs
            for p in doc.paragraphs:
                text = p.text.strip()
                if text:
                    content.append(text)

            # Tables
            table_count = len(doc.tables)
            for table in doc.tables:
                for row in table.rows:
                    row_cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                    if row_cells:
                        content.append(" | ".join(row_cells))

            full_text = "\n\n".join(content)
            if not full_text.strip():
                raise DocumentParseError("The Word document is empty.")

            metadata = {
                "type": "Word Document",
                "paragraph_count": len(doc.paragraphs),
                "table_count": table_count,
                "filename": filename,
            }
            return DocumentParser._sanitize_length(full_text, metadata)

        except Exception as e:
            if isinstance(e, DocumentParseError):
                raise
            # If docx failed on older .doc binary, try plain string extraction
            if filename.lower().endswith(".doc"):
                return DocumentParser._fallback_binary_strings(stream, filename, "Legacy Word (.doc)")
            logger.error("Failed to parse Word document %s: %s", filename, e, exc_info=True)
            raise DocumentParseError(f"Error reading Word document: {e}")

    # --------------------------------------------------------------------------
    # 3. PowerPoint Parser (.pptx, .ppt)
    # --------------------------------------------------------------------------

    @staticmethod
    def _parse_pptx(stream: io.BytesIO, filename: str) -> Tuple[str, dict]:
        try:
            prs = pptx.Presentation(stream)
            total_slides = len(prs.slides)
            extracted_slides = []

            for i, slide in enumerate(prs.slides):
                slide_texts = []
                for shape in slide.shapes:
                    if shape.has_text_frame:
                        for paragraph in shape.text_frame.paragraphs:
                            line = paragraph.text.strip()
                            if line:
                                slide_texts.append(line)

                # Slide notes
                if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                    note_text = slide.notes_slide.notes_text_frame.text.strip()
                    if note_text:
                        slide_texts.append(f"[Speaker Notes: {note_text}]")

                if slide_texts:
                    extracted_slides.append(
                        f"--- [Slide {i + 1}] ---\n" + "\n".join(slide_texts)
                    )

            full_text = "\n\n".join(extracted_slides)
            if not full_text.strip():
                raise DocumentParseError("The PowerPoint slides appear to contain no readable text.")

            metadata = {"type": "PowerPoint Slides", "total_slides": total_slides, "filename": filename}
            return DocumentParser._sanitize_length(full_text, metadata)

        except Exception as e:
            if isinstance(e, DocumentParseError):
                raise
            if filename.lower().endswith(".ppt"):
                return DocumentParser._fallback_binary_strings(stream, filename, "Legacy PowerPoint (.ppt)")
            logger.error("Failed to parse PowerPoint presentation %s: %s", filename, e, exc_info=True)
            raise DocumentParseError(f"Error reading PowerPoint presentation: {e}")

    # --------------------------------------------------------------------------
    # 4. Excel Parser (.xlsx, .xls)
    # --------------------------------------------------------------------------

    @staticmethod
    def _parse_excel(stream: io.BytesIO, filename: str) -> Tuple[str, dict]:
        if not openpyxl:
            raise DocumentParseError("Excel parsing library 'openpyxl' is not installed.")

        try:
            wb = openpyxl.load_workbook(stream, read_only=True, data_only=True)
            sheets_content: List[str] = []
            sheet_names = wb.sheetnames
            total_rows_extracted = 0

            for sheet_name in sheet_names:
                ws = wb[sheet_name]
                sheet_lines = [f"=== Sheet: {sheet_name} ==="]
                row_idx = 0

                for row in ws.iter_rows(values_only=True):
                    # Skip completely empty rows
                    if not any(cell is not None for cell in row):
                        continue

                    row_idx += 1
                    total_rows_extracted += 1

                    # Format row cells cleanly
                    row_cells = []
                    for cell in row:
                        if cell is None:
                            row_cells.append("")
                        elif isinstance(cell, float):
                            row_cells.append(f"{cell:.4g}")
                        else:
                            row_cells.append(str(cell).strip())

                    # Join row with pipe separators
                    sheet_lines.append(" | ".join(row_cells))

                    # Limit to 120 rows per sheet to prevent blowing context tokens
                    if row_idx >= 120:
                        sheet_lines.append(f"[... and {sheet_name} rows continue ...]")
                        break

                if len(sheet_lines) > 1:
                    sheets_content.append("\n".join(sheet_lines))

            wb.close()
            full_text = "\n\n".join(sheets_content)
            if not full_text.strip():
                raise DocumentParseError("The Excel spreadsheet contains no readable data.")

            metadata = {
                "type": "Excel Spreadsheet",
                "sheet_count": len(sheet_names),
                "sheet_names": sheet_names,
                "rows_sample": total_rows_extracted,
                "filename": filename,
            }
            return DocumentParser._sanitize_length(full_text, metadata)

        except Exception as e:
            if isinstance(e, DocumentParseError):
                raise
            if filename.lower().endswith(".xls"):
                return DocumentParser._fallback_binary_strings(stream, filename, "Legacy Excel (.xls)")
            logger.error("Failed to parse Excel file %s: %s", filename, e, exc_info=True)
            raise DocumentParseError(f"Error reading Excel spreadsheet: {e}")

    # --------------------------------------------------------------------------
    # 5. Jupyter Notebook Parser (.ipynb)
    # --------------------------------------------------------------------------

    @staticmethod
    def _parse_jupyter(stream: io.BytesIO, filename: str) -> Tuple[str, dict]:
        try:
            raw_text, _ = DocumentParser._decode_raw_text(stream.getvalue())
            nb = json.loads(raw_text)
            cells = nb.get("cells", [])

            output_lines = [f"=== Jupyter Notebook: {filename} ==="]
            code_cell_count = 0
            md_cell_count = 0

            for idx, cell in enumerate(cells):
                cell_type = cell.get("cell_type", "code")
                source = "".join(cell.get("source", [])).strip()

                if not source:
                    continue

                if cell_type == "markdown":
                    md_cell_count += 1
                    output_lines.append(f"\n[Markdown Cell {idx + 1}]:\n{source}")

                elif cell_type == "code":
                    code_cell_count += 1
                    output_lines.append(f"\n[Code Cell {idx + 1}]:\n```python\n{source}\n```")

                    # Check for execution outputs and error traces
                    outputs = cell.get("outputs", [])
                    for out in outputs:
                        # Error tracebacks
                        if out.get("output_type") == "error":
                            tb = "\n".join(out.get("traceback", []))
                            clean_tb = re.sub(r"\x1b\[[0-9;]*[mK]", "", tb)
                            output_lines.append(f"[Error Traceback]:\n```text\n{clean_tb.strip()}\n```")
                        # Standard text outputs
                        elif "text" in out:
                            text_out = "".join(out.get("text", [])).strip()
                            if text_out:
                                output_lines.append(f"[Cell Output]: {text_out[:300]}")

            full_text = "\n".join(output_lines)
            if not full_text.strip():
                raise DocumentParseError("The Jupyter Notebook is empty.")

            metadata = {
                "type": "Jupyter Notebook",
                "code_cells": code_cell_count,
                "markdown_cells": md_cell_count,
                "filename": filename,
            }
            return DocumentParser._sanitize_length(full_text, metadata)

        except Exception as e:
            if isinstance(e, DocumentParseError):
                raise
            logger.error("Failed to parse Jupyter Notebook %s: %s", filename, e, exc_info=True)
            raise DocumentParseError(f"Error reading Jupyter Notebook: {e}")

    # --------------------------------------------------------------------------
    # 6. Tabular CSV / TSV Parser
    # --------------------------------------------------------------------------

    @staticmethod
    def _parse_csv(stream: io.BytesIO, filename: str, ext: str) -> Tuple[str, dict]:
        try:
            raw_text, encoding = DocumentParser._decode_raw_text(stream.getvalue())
            lines = raw_text.splitlines()
            if not lines:
                raise DocumentParseError("The CSV/TSV file is empty.")

            delimiter = "\t" if ext == "tsv" else ","
            # Sniff delimiter if comma
            if ext == "csv" and len(lines) > 0:
                sample = "\n".join(lines[:5])
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
                    delimiter = dialect.delimiter
                except Exception:
                    delimiter = ","

            reader = csv.reader(lines, delimiter=delimiter)
            formatted_rows: List[str] = [f"=== Tabular Data: {filename} ==="]
            row_count = 0

            for row in reader:
                if not any(cell.strip() for cell in row):
                    continue
                row_count += 1
                formatted_rows.append(" | ".join([c.strip() for c in row]))

                if row_count >= 150:
                    formatted_rows.append(f"[... and {len(lines) - 150} more rows ...]")
                    break

            full_text = "\n".join(formatted_rows)
            metadata = {
                "type": "Tabular (CSV/TSV)",
                "total_rows": len(lines),
                "encoding": encoding,
                "filename": filename,
            }
            return DocumentParser._sanitize_length(full_text, metadata)

        except Exception as e:
            if isinstance(e, DocumentParseError):
                raise
            logger.error("Failed to parse CSV %s: %s", filename, e, exc_info=True)
            raise DocumentParseError(f"Error reading CSV file: {e}")

    # --------------------------------------------------------------------------
    # 7. OpenDocument Parser (.odt, .ods, .odp)
    # --------------------------------------------------------------------------

    @staticmethod
    def _parse_opendocument(stream: io.BytesIO, filename: str, ext: str) -> Tuple[str, dict]:
        try:
            with zipfile.ZipFile(stream) as z:
                if "content.xml" not in z.namelist():
                    raise DocumentParseError("Invalid OpenDocument file structure.")
                if z.getinfo("content.xml").file_size > MAX_ODF_CONTENT_BYTES:
                    raise DocumentParseError("The OpenDocument content is too large to process.")
                xml_data = z.read("content.xml")

            tree = ET.fromstring(xml_data)
            # Extract all text elements
            texts = [elem.text for elem in tree.iter() if elem.text and elem.text.strip()]
            full_text = "\n".join(texts)

            if not full_text.strip():
                raise DocumentParseError("The OpenDocument file contains no readable text.")

            doc_type_names = {"odt": "OpenDocument Text", "ods": "OpenDocument Sheet", "odp": "OpenDocument Presentation"}
            metadata = {"type": doc_type_names.get(ext, "OpenDocument"), "filename": filename}
            return DocumentParser._sanitize_length(full_text, metadata)

        except Exception as e:
            if isinstance(e, DocumentParseError):
                raise
            logger.error("Failed to parse OpenDocument %s: %s", filename, e, exc_info=True)
            raise DocumentParseError(f"Error reading OpenDocument file: {e}")

    # --------------------------------------------------------------------------
    # 8. Rich Text Format Parser (.rtf)
    # --------------------------------------------------------------------------

    @staticmethod
    def _parse_rtf(stream: io.BytesIO, filename: str) -> Tuple[str, dict]:
        try:
            raw_text, encoding = DocumentParser._decode_raw_text(stream.getvalue())
            # Strip RTF control words and groups
            cleaned = re.sub(r"\\[a-zA-Z0-9\-]+", " ", raw_text)
            cleaned = re.sub(r"[{}\\]", "", cleaned)
            cleaned = "\n".join([line.strip() for line in cleaned.splitlines() if line.strip()])

            if not cleaned.strip():
                raise DocumentParseError("The RTF document is empty.")

            metadata = {"type": "Rich Text (RTF)", "encoding": encoding, "filename": filename}
            return DocumentParser._sanitize_length(cleaned, metadata)

        except Exception as e:
            if isinstance(e, DocumentParseError):
                raise
            logger.error("Failed to parse RTF %s: %s", filename, e, exc_info=True)
            raise DocumentParseError(f"Error reading RTF document: {e}")

    # --------------------------------------------------------------------------
    # 9. Markup Parser (HTML, XML, SVG)
    # --------------------------------------------------------------------------

    @staticmethod
    def _parse_markup(stream: io.BytesIO, filename: str) -> Tuple[str, dict]:
        try:
            raw_text, encoding = DocumentParser._decode_raw_text(stream.getvalue())
            # Strip scripts and styles
            cleaned = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", raw_text, flags=re.DOTALL | re.IGNORECASE)
            # Convert basic block tags to newlines
            cleaned = re.sub(r"</?(p|div|h[1-6]|li|tr|br)[^>]*>", "\n", cleaned, flags=re.IGNORECASE)
            # Remove remaining tags
            cleaned = re.sub(r"<[^>]+>", "", cleaned)
            # Unescape entities
            cleaned = html.unescape(cleaned)
            cleaned = "\n".join([line.strip() for line in cleaned.splitlines() if line.strip()])

            if not cleaned.strip():
                raise DocumentParseError("The markup document contains no readable text.")

            metadata = {"type": "Markup (HTML/XML)", "encoding": encoding, "filename": filename}
            return DocumentParser._sanitize_length(cleaned, metadata)

        except Exception as e:
            if isinstance(e, DocumentParseError):
                raise
            logger.error("Failed to parse markup %s: %s", filename, e, exc_info=True)
            raise DocumentParseError(f"Error reading HTML/XML document: {e}")

    # --------------------------------------------------------------------------
    # 10. Source Code & General Text Parser
    # --------------------------------------------------------------------------

    @staticmethod
    def _parse_text(stream: io.BytesIO, filename: str) -> Tuple[str, dict]:
        raw_text, encoding = DocumentParser._decode_raw_text(stream.getvalue())
        ext = filename.lower().split(".")[-1]
        metadata = {"type": f"Source/Text (.{ext})", "encoding": encoding, "filename": filename}
        return DocumentParser._sanitize_length(raw_text, metadata)

    # --------------------------------------------------------------------------
    # Helper Utilities
    # --------------------------------------------------------------------------

    @staticmethod
    def _decode_raw_text(raw_bytes: bytes) -> Tuple[str, str]:
        """Decode raw bytes trying common text encodings."""
        # utf-8-sig first: it also decodes plain UTF-8, and strips a BOM that breaks json.loads
        encodings = ["utf-8-sig", "cp1252", "latin-1"]
        for enc in encodings:
            try:
                return raw_bytes.decode(enc), enc
            except UnicodeDecodeError:
                continue
        # Fallback with replacement
        return raw_bytes.decode("utf-8", errors="replace"), "utf-8 (replace)"

    @staticmethod
    def _looks_like_text(raw_bytes: bytes) -> bool:
        """Heuristic: text files have no NUL bytes and decode as UTF-8 (sampled from the head)."""
        sample = raw_bytes[:8192]
        if b"\x00" in sample:
            return False
        try:
            sample.decode("utf-8")
        except UnicodeDecodeError as e:
            # A multi-byte character cut off at the sample boundary is still text
            return e.start >= len(sample) - 3
        return True

    @staticmethod
    def _fallback_binary_strings(stream: io.BytesIO, filename: str, doc_type: str) -> Tuple[str, dict]:
        """Extract ASCII/printable strings from older proprietary binary files."""
        data = stream.getvalue()
        words = re.findall(b"[\x20-\x7E\t\r\n]{4,}", data)
        extracted = "\n".join([w.decode("latin-1", errors="ignore") for w in words])
        if not extracted.strip():
            raise DocumentParseError(f"Could not extract readable text from {doc_type} file '{filename}'.")

        metadata = {"type": f"{doc_type} (Text Extracted)", "filename": filename}
        return DocumentParser._sanitize_length(extracted, metadata)

    @staticmethod
    def _sanitize_length(text: str, metadata: dict) -> Tuple[str, dict]:
        """Truncate text if it exceeds maximum extraction threshold."""
        total_len = len(text)
        metadata["total_characters"] = total_len

        if total_len > MAX_EXTRACTED_CHARS:
            truncated = (
                text[:MAX_EXTRACTED_CHARS]
                + f"\n\n[... Truncated: Document contains {total_len} characters; analyzing first {MAX_EXTRACTED_CHARS} characters ...]"
            )
            metadata["is_truncated"] = True
            return truncated, metadata

        metadata["is_truncated"] = False
        return text, metadata


document_parser = DocumentParser()
