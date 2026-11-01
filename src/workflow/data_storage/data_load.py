"""提取正文；PDF 保留页码，Word 按正文顺序读取段落与表格。"""

from pathlib import Path

SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}


def load_document(file_path: str | Path, max_chars: int = 5_000_000) -> list[dict]:
    path = Path(file_path)
    units = []
    total = 0

    def append(text, **metadata):
        nonlocal total
        total += len(text)
        if total > max_chars:
            raise ValueError("文档正文超过字符数限制")
        if text.strip():
            units.append({"text": text, "metadata": metadata})

    suffix = path.suffix.lower()
    if suffix in {".txt", ".md"}:
        append(path.read_text(encoding="utf-8-sig"))
    elif suffix == ".pdf":
        from pypdf import PdfReader

        with path.open("rb") as source:
            reader = PdfReader(source)
            if reader.is_encrypted:
                raise ValueError("不支持加密 PDF")
            for number, page in enumerate(reader.pages, 1):
                append(page.extract_text() or "", page_number=number)
    elif suffix == ".docx":
        from docx import Document
        from docx.table import Table

        document = Document(path)
        for index, item in enumerate(document.iter_inner_content()):
            if isinstance(item, Table):
                rows = []
                for row in item.rows:
                    seen, cells = set(), []
                    for cell in row.cells:
                        if cell._tc not in seen:
                            seen.add(cell._tc)
                            cells.append(cell.text)
                    rows.append("\t".join(cells))
                append("\n".join(rows), element_index=index, type="table")
            else:
                append(item.text, element_index=index, type="paragraph")
    else:
        raise ValueError("仅支持 PDF、DOCX、MD、TXT 文件")
    if not units:
        raise ValueError("文档没有可提取的正文；扫描 PDF 需先做 OCR")
    return units
