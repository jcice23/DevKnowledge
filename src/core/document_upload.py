"""保存上传文档；后续解析器可通过 upload_dir / stored_filename 读取文件。"""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4


ALLOWED_EXTENSIONS = {".pdf", ".docx", ".md", ".txt"}
CHUNK_SIZE = 1024 * 1024


class UploadValidationError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class UploadedDocument:
    document_id: str
    original_filename: str
    stored_filename: str
    size_bytes: int
    sha256: str
    status: str = "uploaded"


def save_document(
    source: BinaryIO, filename: str | None, upload_dir: Path, max_bytes: int,
) -> UploadedDocument:
    """分块保存并计算摘要；校验失败或写入异常时清理本次创建的文件。

    这里只校验扩展名和大小，文档是否可解析由后续解析阶段确认。
    SHA-256 用于后续去重判断，上传阶段允许重复上传。
    """
    if max_bytes <= 0:
        raise ValueError("上传大小限制必须大于 0")
    if not filename or not filename.strip():
        raise UploadValidationError("文件名不能为空")
    # 同时处理 Windows 和 POSIX 路径，客户端文件名只作为展示元数据。
    original_filename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    extension = Path(original_filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise UploadValidationError("仅支持 PDF、DOCX、MD、TXT 文件", 415)

    document_id = uuid4().hex
    stored_filename = document_id + extension
    upload_dir.mkdir(parents=True, exist_ok=True)
    destination = upload_dir / stored_filename
    digest = hashlib.sha256()
    size = 0
    created = False
    try:
        with destination.open("xb") as target:
            created = True
            while chunk := source.read(min(CHUNK_SIZE, max_bytes - size + 1)):
                size += len(chunk)
                if size > max_bytes:
                    raise UploadValidationError(f"文件大小不能超过 {max_bytes} 字节", 413)
                target.write(chunk)
                digest.update(chunk)
            if size == 0:
                raise UploadValidationError("不能上传空文件")
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)
        raise

    return UploadedDocument(
        document_id=document_id,
        original_filename=original_filename,
        stored_filename=stored_filename,
        size_bytes=size,
        sha256=digest.hexdigest(),
    )
