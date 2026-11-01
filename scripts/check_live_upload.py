"""真实上传→入库→问答联调。会保留一份小型测试文档及其向量，不删除现有数据。"""
import asyncio
import json
import os
import argparse
from pathlib import Path

import httpx

os.environ.setdefault('LOG_FILE', './logs/live-upload.log')
from main import app


async def check(document_id=None):
    report = {'passed': False}
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test', timeout=180) as client:
                if document_id:
                    response = await client.get(f'/documents/{document_id}')
                    assert response.status_code == 200, 'document missing'
                    if response.json()['data']['status'] == 'failed':
                        response = await client.post(f'/documents/{document_id}/retry')
                        assert response.status_code == 202, 'retry failed'
                else:
                    response = await client.post('/upload', files={'file': (
                        'JC自动入库联调.txt',
                        '这是一份 JC 上传自动入库功能的联调资料。联调验证口令为：松林里的纸飞机。此口令仅用于功能测试。'.encode(),
                        'text/plain',
                    )})
                    assert response.status_code == 201, f'upload HTTP {response.status_code}'
                    document_id = response.json()['data']['document_id']
                report['document_id'] = document_id
                for _ in range(150):
                    response = await client.get(f'/documents/{document_id}')
                    record = response.json()['data']
                    if record['status'] in ('ready', 'failed'):
                        break
                    await asyncio.sleep(2)
                report['document'] = record
                assert record['status'] == 'ready', f"ingestion {record['status']}"
                response = await client.post('/chat', json={
                    'user_input': 'JC 自动入库功能的联调验证口令是什么？', 'document_ids': [document_id],
                })
                report['chat_status'] = response.status_code
                report['chat'] = response.json()
                assert response.status_code == 200, f'chat HTTP {response.status_code}'
                assert '松林里的纸飞机' in response.json()['data'], 'answer missing expected evidence'
                citations = response.json()['citations']
                assert citations and all(c['document_id'] == document_id for c in citations), 'invalid source'
                assert all(c['ingestion_id'] == record['ingestion_id'] for c in citations), 'invalid version'
                report['passed'] = True
    except Exception as exc:
        report['error_type'] = type(exc).__name__
        if isinstance(exc, AssertionError):
            report['error'] = str(exc)
    path = Path('output/live_upload_report.json')
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('passed', 'document_id', 'error_type', 'error') if k in report}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--document-id', help='复用之前的联调文档，失败时重试，不重复上传')
    args = parser.parse_args()
    raise SystemExit(asyncio.run(check(args.document_id)))
