"""文件保存到项目目录，持久队列负责入库；状态接口不返回文件内容。"""

import logging

from fastapi import APIRouter, File, HTTPException, UploadFile, Request
from pydantic import BaseModel

from configs.settings import settings
from src.core.document_upload import UploadValidationError, save_document


logger = logging.getLogger(__name__)
router = APIRouter(tags=["文档"])


class UploadResponse(BaseModel):
    success: bool = True
    message: str = "上传成功，已加入入库队列"
    data: dict


@router.post("/upload", response_model=UploadResponse, status_code=201, summary="上传文档")
def upload_document(request: Request, file: UploadFile = File(...)) -> UploadResponse:
    # 同步路由由 FastAPI 在线程池中执行，磁盘读写不会阻塞异步事件循环。
    try:
        registry = get_registry(request)
        document = save_document(
            file.file, file.filename, settings.upload_dir, settings.upload_max_bytes,
        )
        try:
            record = registry.add(document, settings.milvus_collection)
        except Exception:
            # 元数据提交失败时，本次上传不能成为无状态的孤立文件。
            (settings.upload_dir / document.stored_filename).unlink(missing_ok=True)
            logger.error("文档状态保存失败")
            raise HTTPException(status_code=503, detail="文档状态服务不可用，请重新上传")
        return UploadResponse(data=record)
    except UploadValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except OSError as exc:
        logger.exception("上传文档保存失败")
        raise HTTPException(status_code=500, detail="文件保存失败，请稍后重试") from exc
    finally:
        file.file.close()


def get_registry(request: Request):
    registry = getattr(request.app.state, 'document_registry', None)
    if registry is None:
        raise HTTPException(status_code=503, detail="文档状态服务未就绪")
    return registry


@router.get('/documents', summary='查看上传文档状态')
def list_documents(request: Request):
    return {'data': get_registry(request).list(settings.milvus_collection),
            'worker_available': getattr(request.app.state, 'document_worker', None) is not None}


@router.get('/documents/{document_id}', summary='查看单个文档状态')
def get_document(document_id: str, request: Request):
    record = get_registry(request).get(document_id)
    if record is None or record['collection_name'] != settings.milvus_collection:
        raise HTTPException(status_code=404, detail='文档不存在')
    return {'data': record}


@router.post('/documents/{document_id}/retry', status_code=202, summary='重试失败文档')
def retry_document(document_id: str, request: Request):
    get_document(document_id, request)
    registry = get_registry(request)
    if not registry.retry(document_id):
        raise HTTPException(status_code=409, detail='仅失败文档可以重试，请刷新状态')
    return {'data': registry.get(document_id)}
