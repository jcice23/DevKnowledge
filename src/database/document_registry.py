"""SQLite 只保存文档元数据和任务状态，原始文件仍留在上传目录。"""

import sqlite3
import time
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4


class DocumentRegistry:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS documents (
                document_id TEXT PRIMARY KEY, original_filename TEXT NOT NULL,
                stored_filename TEXT NOT NULL, size_bytes INTEGER NOT NULL, sha256 TEXT NOT NULL,
                collection_name TEXT NOT NULL, status TEXT NOT NULL, error TEXT,
                ingestion_id TEXT, chunk_count INTEGER, embedding_dimension INTEGER,
                created_at REAL NOT NULL, updated_at REAL NOT NULL,
                lease_until REAL, claim_token TEXT
            )""")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def public(row):
        return {k: row[k] for k in row.keys() if k not in ('lease_until', 'claim_token')}

    def add(self, document, collection):
        values = asdict(document)
        values.update(collection_name=collection, status='queued', now=time.time())
        with self.connect() as db:
            db.execute("""INSERT INTO documents
                (document_id, original_filename, stored_filename, size_bytes, sha256,
                 collection_name, status, created_at, updated_at)
                VALUES (:document_id,:original_filename,:stored_filename,:size_bytes,:sha256,
                        :collection_name,:status,:now,:now)""", values)
        return self.get(document.document_id)

    def get(self, document_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM documents WHERE document_id=?', (document_id,)).fetchone()
            return self.public(row) if row else None

    def list(self, collection):
        with self.connect() as db:
            return [self.public(r) for r in db.execute(
                'SELECT * FROM documents WHERE collection_name=? ORDER BY created_at DESC', (collection,))]

    def retry(self, document_id):
        with self.connect() as db:
            return db.execute("""UPDATE documents SET status='queued', error=NULL, updated_at=?
                WHERE document_id=? AND status='failed'""", (time.time(), document_id)).rowcount == 1

    def claim(self, collection):
        now, token = time.time(), uuid4().hex
        with self.connect() as db:
            # 短事务原子领取；进程退出后，过期租约允许另一工作进程继续任务。
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("""SELECT * FROM documents WHERE collection_name=? AND
                (status='queued' OR (status='processing' AND lease_until<?))
                ORDER BY created_at LIMIT 1""", (collection, now)).fetchone()
            if row is None:
                return None
            db.execute("""UPDATE documents SET status='processing', claim_token=?, lease_until=?,
                updated_at=? WHERE document_id=?""", (token, now + 90, now, row['document_id']))
            return {**dict(row), 'claim_token': token}

    def heartbeat(self, document_id, token):
        with self.connect() as db:
            db.execute('UPDATE documents SET lease_until=? WHERE document_id=? AND claim_token=?',
                       (time.time() + 90, document_id, token))

    def finish(self, document_id, token, result=None):
        with self.connect() as db:
            # 只有当前租约所有者可以发布版本，部分写入永远不进入有效版本列表。
            db.execute("""UPDATE documents SET status=?, error=?, ingestion_id=?, chunk_count=?,
                embedding_dimension=?, updated_at=?, lease_until=NULL, claim_token=NULL
                WHERE document_id=? AND claim_token=?""", (
                'ready' if result else 'failed', None if result else '入库失败，请检查文档内容及模型、向量服务配置后重试。',
                result.ingestion_id if result else None, result.chunk_count if result else None,
                result.embedding_dimension if result else None, time.time(), document_id, token))

    def release(self, document_id, token):
        with self.connect() as db:
            db.execute("""UPDATE documents SET status='queued', lease_until=NULL, claim_token=NULL
                WHERE document_id=? AND claim_token=?""", (document_id, token))

    def versions(self, collection):
        with self.connect() as db:
            return [r[0] for r in db.execute("""SELECT ingestion_id FROM documents
                WHERE collection_name=? AND status='ready' AND ingestion_id IS NOT NULL""", (collection,))]
