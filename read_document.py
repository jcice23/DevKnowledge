from dataclasses import dataclass
from pathlib import Path

# 定义后续环节接收的统一结构，避免分块逻辑依赖某个解析库
@dataclass
class LoadedDocument:
    text:str
    source_path:str
    page_number:int | None = None
    heading:str | None = None

def load_markdown(file_path:str | Path) -> LoadedDocument:
    path=Path(file_path)

    if path.suffix.lower() != ".md":
        raise ValueError(f"只支持Markdown{path}")
    # 文件不存在或无法访问时，让Python抛出对应异常
    text=path.read_text(encoding="utf-8-sig")

    if not text.strip():
        raise ValueError(f"文档正文为空：{path}")

    return LoadedDocument(
        text=text,
        source_path=str(path.resolve())
    )

if __name__ == "__main__":
    document=load_markdown(
        Path(__file__).parent
        / "data"
        / "agent连接微信ClawBot教程.md"
    )

    print(f"来源:{document.source_path}")
    print(f"正文字符数:{len(document.text)}")
    print(f"页码:{document.page_number}")
    print(f"章节:{document.heading}")
    print(f"\n===== 正文预览 =====\n")
    print(f"document.text[:20000]")