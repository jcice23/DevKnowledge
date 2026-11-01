"""服务器会话存储。短事务保护领取、去重和摘要提交；模型调用不占用事务。"""
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


class ConversationError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message
        super().__init__(message)


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


class ConversationStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at REAL NOT NULL,
                    updated_at REAL NOT NULL, summary TEXT NOT NULL DEFAULT '',
                    summary_seq INTEGER NOT NULL DEFAULT 0, next_seq INTEGER NOT NULL DEFAULT 1,
                    import_id TEXT UNIQUE);
                CREATE TABLE IF NOT EXISTS turns (
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    request_id TEXT NOT NULL, seq INTEGER NOT NULL, input_json TEXT NOT NULL,
                    messages_json TEXT NOT NULL, status TEXT NOT NULL, error TEXT,
                    response_json TEXT, retrieval_query TEXT, claim_token TEXT, lease_until REAL,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    PRIMARY KEY (conversation_id, request_id), UNIQUE(conversation_id, seq));
                CREATE INDEX IF NOT EXISTS conversations_updated ON conversations(updated_at DESC);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def recover(db):
        db.execute("""UPDATE turns SET status='failed', error='处理已中断或超时，请重试',
            claim_token=NULL, lease_until=NULL, updated_at=?
            WHERE status='processing' AND lease_until<=?""", (time.time(), time.time()))

    @staticmethod
    def conversation(db, conversation_id):
        row = db.execute('SELECT * FROM conversations WHERE id=?', (conversation_id,)).fetchone()
        if row is None:
            raise ConversationError(404, '会话不存在或已删除')
        return dict(row)

    @staticmethod
    def turn(row):
        return {k: row[k] for k in ('request_id', 'seq', 'status', 'error', 'created_at', 'updated_at')} | {
            'messages': json.loads(row['messages_json']),
            'request': json.loads(row['input_json']),
            'response': json.loads(row['response_json']) if row['response_json'] else None,
            'retrieval_query': row['retrieval_query'],
        }

    def create(self):
        now, cid = time.time(), uuid4().hex
        with self.connect() as db:
            db.execute('INSERT INTO conversations (id,title,created_at,updated_at) VALUES (?,?,?,?)',
                       (cid, '新的开始', now, now))
            return self.conversation(db, cid)

    def list(self, limit=50, offset=0):
        with self.connect() as db:
            self.recover(db)
            rows = db.execute('SELECT id,title,created_at,updated_at FROM conversations '
                              'ORDER BY updated_at DESC,id LIMIT ? OFFSET ?', (limit + 1, offset)).fetchall()
            return {'data': [dict(r) for r in rows[:limit]],
                    'next_offset': offset + limit if len(rows) > limit else None}

    def history(self, cid, limit=50, before=None):
        with self.connect() as db:
            self.recover(db)
            conversation = self.conversation(db, cid)
            rows = db.execute('SELECT * FROM turns WHERE conversation_id=? AND seq<? '
                              'ORDER BY seq DESC LIMIT ?', (cid, before or 2**63-1, limit + 1)).fetchall()
            processing = db.execute("SELECT request_id FROM turns WHERE conversation_id=? AND status='processing'",
                                    (cid,)).fetchone()
            return {'conversation': conversation, 'data': [self.turn(r) for r in reversed(rows[:limit])],
                    'next_before': rows[limit-1]['seq'] if len(rows) > limit else None,
                    'processing_request_id': processing[0] if processing else None}

    def request_status(self, cid, rid):
        with self.connect() as db:
            self.recover(db)
            self.conversation(db, cid)
            row = db.execute('SELECT * FROM turns WHERE conversation_id=? AND request_id=?', (cid, rid)).fetchone()
            if not row:
                raise ConversationError(404, '请求尚未创建')
            return self.turn(row)

    def delete(self, cid):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self.recover(db)
            self.conversation(db, cid)
            if db.execute("SELECT 1 FROM turns WHERE conversation_id=? AND status='processing'", (cid,)).fetchone():
                raise ConversationError(409, '会话正在处理中，请稍后删除')
            db.execute('DELETE FROM conversations WHERE id=?', (cid,))

    def claim(self, cid, rid, payload, lease_seconds):
        now, token = time.time(), uuid4().hex
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self.recover(db)
            conversation = self.conversation(db, cid)
            old = db.execute('SELECT * FROM turns WHERE conversation_id=? AND request_id=?', (cid, rid)).fetchone()
            if old:
                if old['input_json'] != encode(payload):
                    raise ConversationError(409, '同一请求标识不能用于不同的问题或参数')
                if old['status'] == 'completed':
                    return {'cached': json.loads(old['response_json'])}
            if db.execute("SELECT 1 FROM turns WHERE conversation_id=? AND status='processing'", (cid,)).fetchone():
                raise ConversationError(409, '此会话正在处理另一个请求，请等待结果')
            seq = conversation['next_seq']
            message = {'id': rid + '-user', 'role': 'user', 'text': payload['user_input'], 'mode': payload['mode']}
            # 重试复用原记录并移动到当前末尾，使摘要覆盖位置始终单调前进。
            db.execute("""INSERT INTO turns
                (conversation_id,request_id,seq,input_json,messages_json,status,claim_token,lease_until,created_at,updated_at)
                VALUES (?,?,?,?,?,'processing',?,?,?,?) ON CONFLICT(conversation_id,request_id) DO UPDATE SET
                seq=excluded.seq,status='processing',error=NULL,claim_token=excluded.claim_token,
                lease_until=excluded.lease_until,updated_at=excluded.updated_at""",
                (cid, rid, seq, encode(payload), encode([message]), token, now + lease_seconds, now, now))
            db.execute("UPDATE conversations SET next_seq=?,updated_at=?,title=CASE WHEN next_seq=1 THEN ? ELSE title END WHERE id=?",
                       (seq + 1, now, payload['user_input'][:24], cid))
            history = db.execute("SELECT * FROM turns WHERE conversation_id=? AND status='completed' AND seq>? ORDER BY seq",
                                 (cid, conversation['summary_seq'])).fetchall()
            return {'token': token, 'summary': conversation['summary'], 'summary_seq': conversation['summary_seq'],
                    'turns': [self.turn(r) for r in history]}

    def complete(self, cid, rid, token, response, summary, summary_seq, query):
        now = time.time()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM turns WHERE conversation_id=? AND request_id=? AND claim_token=? "
                             "AND status='processing' AND lease_until>?", (cid, rid, token, now)).fetchone()
            if row is None:
                raise ConversationError(409, '请求已过期，请刷新会话状态')
            messages = json.loads(row['messages_json']) + [{'id': rid + '-assistant', 'role': 'assistant',
                'text': response['data'], 'mode': response['mode'], 'citations': response['citations']}]
            db.execute("""UPDATE turns SET status='completed',messages_json=?,response_json=?,retrieval_query=?,
                claim_token=NULL,lease_until=NULL,updated_at=? WHERE conversation_id=? AND request_id=?""",
                (encode(messages), encode(response), query, now, cid, rid))
            db.execute('UPDATE conversations SET summary=?,summary_seq=?,updated_at=? WHERE id=?',
                       (summary, summary_seq, now, cid))

    def fail(self, cid, rid, token, message):
        with self.connect() as db:
            db.execute("""UPDATE turns SET status='failed',error=?,claim_token=NULL,lease_until=NULL,updated_at=?
                WHERE conversation_id=? AND request_id=? AND claim_token=? AND status='processing'""",
                (message, time.time(), cid, rid, token))

    def import_history(self, source_id, title, messages):
        now, cid = time.time(), uuid4().hex
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT id FROM conversations WHERE import_id=?', (source_id,)).fetchone()
            if old:
                return self.conversation(db, old[0])
            db.execute('INSERT INTO conversations (id,title,created_at,updated_at,import_id) VALUES (?,?,?,?,?)',
                       (cid, title[:24], now, now, source_id))
            index, seq = 0, 1
            while index < len(messages):
                group = [messages[index]]
                if group[0]['role'] == 'user' and index + 1 < len(messages) and messages[index+1]['role'] == 'assistant':
                    group.append(messages[index+1])
                complete = len(group) == 2
                rid = uuid4().hex
                for pos, message in enumerate(group):
                    message = dict(message)
                    message['id'] = rid + f'-{pos}'
                    group[pos] = message
                payload = {'user_input': group[0]['text'], 'mode': group[0]['mode']}
                db.execute("""INSERT INTO turns (conversation_id,request_id,seq,input_json,messages_json,status,
                    created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)""",
                    (cid, rid, seq, encode(payload), encode(group), 'completed' if complete else 'imported', now, now))
                index += len(group)
                seq += 1
            db.execute('UPDATE conversations SET next_seq=? WHERE id=?', (seq, cid))
            return self.conversation(db, cid)
