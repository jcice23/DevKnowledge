"""真实服务联调（调用配置的模型，读取 Milvus；不执行入库或删除）。
运行：python -m scripts.check_live_chat
"""
import asyncio
import datetime
import json
import logging
from pathlib import Path

import httpx

from main import app
from configs.settings import settings
from src.workflow.rag_chat import NO_INFORMATION


async def check():
    result = {'checked_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'checks': []}
    try:
        async with app.router.lifespan_context(app):
            logging.getLogger('pymilvus').setLevel(logging.CRITICAL)
            service = app.state.rag_chat
            if service is None:
                raise RuntimeError('RAG initialization unavailable')
            retriever = service.retriever
            database = retriever.database
            report = json.loads(settings.rag_ingestion_report.read_text(encoding='utf-8'))
            entries = [item for item in report['successes']
                       if item['collection_name'] == settings.milvus_collection]
            assert report['mode'] == 'ingest' and entries, 'No successful ingestion versions'
            schema = await database.describe_collection(settings.milvus_collection)
            assert schema['description'] == f'DevKnowledge:v1:embedding={retriever.embedder.embedding_id}'
            dimension = next(f['params']['dim'] for f in schema['fields'] if f['name'] == 'embedding')
            await database.load_collection(settings.milvus_collection)
            for item in entries:
                count = await database.query(
                    settings.milvus_collection, filter='ingestion_id == {version}',
                    filter_params={'version': item['ingestion_id']}, output_fields=['count(*)'],
                )
                actual = count[0]['count(*)']
                assert actual == item['chunk_count'], 'Stored chunk count differs from report'
                assert int(dimension) == item['embedding_dimension']
                result['checks'].append({'version': item['ingestion_id'], 'chunks': actual,
                                         'dimension': int(dimension), 'schema_and_count': 'passed'})
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url='http://test', timeout=180) as client:
                for label, body in (
                    ('rag', {'user_input': '正则表达式中的 \\d 表示什么？请给出匹配数字的简单例子。'}),
                    ('no_evidence', {'user_input': '问题', 'document_ids': []}),
                    ('chat', {'user_input': '请只回复：你好', 'mode': 'chat'}),
                ):
                    response = await client.post('/chat', json=body)
                    data = response.json()
                    result['checks'].append({'case': label, 'status': response.status_code, 'response': data})
                    assert response.status_code == 200, f'{label} HTTP {response.status_code}'
                    if label == 'rag':
                        assert data['citations'] and data['data'] != NO_INFORMATION, 'Missing evidence'
                        for citation in data['citations']:
                            rows = await database.query(settings.milvus_collection, ids=[citation['chunk_id']],
                                                        output_fields=['text', 'ingestion_id', 'filename'])
                            assert rows and rows[0]['text'] == citation['text'], 'Citation text differs'
                            assert rows[0]['ingestion_id'] == citation['ingestion_id']
                            assert f"[{citation['number']}]" in data['data']
                    elif label == 'no_evidence':
                        assert data['data'] == NO_INFORMATION and not data['citations']
                    else:
                        assert data['mode'] == 'chat' and data['data'] and not data['citations']
            result['passed'] = True
    except Exception as exc:
        result['passed'] = False
        # 不输出第三方异常原文，避免连接地址/凭据泄露。
        result['error_type'] = type(exc).__name__
        if isinstance(exc, AssertionError):
            result['error'] = str(exc)
    target = Path('output/live_chat_report.json')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'passed': result['passed'], 'checks': len(result['checks']),
                      'error_type': result.get('error_type'), 'report': str(target)}))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(asyncio.run(check()))
