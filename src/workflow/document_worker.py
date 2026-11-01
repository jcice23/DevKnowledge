"""持久队列的异步消费者；复用现有入库流程和应用客户端。"""

import asyncio
import logging
from contextlib import suppress
from dataclasses import replace

from src.workflow.data_storage.config import StorageConfig
from src.workflow.data_storage.embedding import EmbeddingClient
from src.workflow.data_storage.pipeline import ingest_document

logger = logging.getLogger(__name__)


class DocumentWorker:
    def __init__(self, registry, upload_dir, collection, llm, database):
        self.registry, self.upload_dir, self.collection = registry, upload_dir, collection
        self.llm, self.database = llm, database
        self.task = None

    def start(self):
        self.task = asyncio.create_task(self.run())

    async def close(self):
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task

    async def keep_alive(self, job):
        while True:
            await asyncio.sleep(25)
            await asyncio.to_thread(self.registry.heartbeat, job['document_id'], job['claim_token'])

    async def process(self, job):
        heartbeat = asyncio.create_task(self.keep_alive(job))
        try:
            config = replace(StorageConfig.from_env(), collection_name=self.collection)
            result = await ingest_document(
                self.upload_dir / job['stored_filename'], document_id=job['document_id'],
                original_filename=job['original_filename'], config=config,
                embedder=EmbeddingClient(batch_size=config.embedding_batch_size, llm_client=self.llm),
                database=self.database,
            )
            await asyncio.to_thread(self.registry.finish, job['document_id'], job['claim_token'], result)
        except asyncio.CancelledError:
            await asyncio.to_thread(self.registry.release, job['document_id'], job['claim_token'])
            raise
        except Exception as exc:
            logger.error('文档 %s 入库失败：%s', job['document_id'], type(exc).__name__)
            await asyncio.to_thread(self.registry.finish, job['document_id'], job['claim_token'])
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat

    async def run(self):
        while True:
            try:
                job = await asyncio.to_thread(self.registry.claim, self.collection)
                if job:
                    await self.process(job)
                else:
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error('文档队列暂不可用：%s', type(exc).__name__)
                await asyncio.sleep(5)
