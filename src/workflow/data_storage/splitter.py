"""清洗并按字符分块，优先在后半段的换行或句尾切分。"""

import re
import unicodedata

from .config import StorageConfig


def split_documents(units: list[dict], config: StorageConfig) -> list[dict]:
    chunks = []
    for index, unit in enumerate(units):
        text = unicodedata.normalize("NFC", unit["text"])
        text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\ufeff", "")
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
        text = "\n".join(line.rstrip() for line in text.split("\n"))
        text = re.sub(r"\n{3,}", "\n\n", text).strip("\n")
        start = 0
        while start < len(text):
            end = min(start + config.chunk_size, len(text))
            if end < len(text):
                lower = start + max(config.chunk_size // 2, config.chunk_overlap + 1)
                boundaries = list(re.finditer(r"\n|[。！？!?]|\.(?=\s)", text[lower:end]))
                if boundaries:
                    end = lower + boundaries[-1].end()
            if text[start:end].strip():
                chunks.append({
                    "text": text[start:end],
                    "metadata": {**unit["metadata"], "unit_index": index,
                                 "start_index": start, "end_index": end,
                                 "offset_basis": "cleaned_unit", "method": "character_boundary"},
                })
                if len(chunks) > config.max_chunks:
                    raise ValueError("文档分块数量超过限制")
            if end == len(text):
                break
            start = end - config.chunk_overlap
    if not chunks:
        raise ValueError("清洗后没有可入库的正文")
    return chunks
