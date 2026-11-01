"""把检索结果转换为有编号的参考材料，不负责调用聊天模型。"""

from dataclasses import dataclass

from .pipeline import RetrievalHit


@dataclass(frozen=True)
class RetrievalContext:
    text: str
    citations: list[RetrievalHit]  # citations[0] 对应正文中的 [1]


def build_context(hits: list[RetrievalHit], max_chars: int = 12000) -> RetrievalContext:
    """按排名装入完整片段；预算包括标题和分隔符，避免截断后来源范围失真。"""
    if type(max_chars) is not int or max_chars < 1:
        raise ValueError("max_chars 必须是正整数")
    blocks, citations = [], []
    used = 0
    for hit in hits:
        if not hit.text.strip():
            continue
        page = hit.metadata.get("page_number")
        label = hit.filename + (f"，第 {page} 页" if page is not None else "")
        block = f"[{len(citations) + 1}] {label}\n{hit.text}"
        size = len(block) + (2 if blocks else 0)
        if used + size > max_chars:
            continue
        blocks.append(block)
        citations.append(hit)
        used += size
    return RetrievalContext("\n\n".join(blocks), citations)
