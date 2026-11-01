"""真实多轮联调：保留测试会话，调用现有模型及检索，不上传或删除文档。"""
import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

os.environ.setdefault('LOG_FILE', './logs/live-conversations.log')

import httpx
from main import app


async def check():
    report = {'passed': False, 'checks': []}
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test', timeout=180) as client:
                cid = (await client.post('/conversations')).json()['data']['id']
                report['conversation_id'] = cid
                cases = [
                    ('preference', 'chat', '多轮功能联调：项目代号是松林计划，界面强调色是青绿色。请记住这两个信息，简短确认。'),
                    ('followup', 'chat', '刚才的项目代号是什么？'),
                    ('rag_topic_switch', 'rag', '换一个主题：正则表达式中的 \\d 表示什么？'),
                    ('rag_followup', 'rag', '它和 \\w 有什么区别？'),
                    ('back_to_chat', 'chat', '上一个问题比较的两个正则表达式是什么？'),
                    ('recent_1', 'chat', '继续使用简洁中文。只回复收到。'),
                    ('recent_2', 'chat', '接下来继续聊项目。只回复好的。'),
                    ('summary_recall', 'chat', '最早提到的项目代号和界面强调色分别是什么？'),
                ]
                for label, mode, question in cases:
                    rid = uuid4().hex
                    response = await client.post('/chat', json=dict(conversation_id=cid, request_id=rid,
                                                                    user_input=question, mode=mode))
                    body = response.json()
                    report['checks'].append({'case': label, 'status': response.status_code, 'response': body})
                    assert response.status_code == 200, f'{label} HTTP {response.status_code}'
                    if label == 'followup':
                        assert '松林计划' in body['data'], 'followup missed user information'
                    if mode == 'rag':
                        assert body['citations'], f'{label} missing citations'
                        service = app.state.rag_chat
                        for citation in body['citations']:
                            rows = await service.retriever.database.query(service.retriever.collection_name,
                                ids=[citation['chunk_id']], output_fields=['text','ingestion_id'])
                            assert rows and rows[0]['text'] == citation['text'], 'citation text mismatch'
                            assert rows[0]['ingestion_id'] == citation['ingestion_id'], 'citation version mismatch'
                    if label == 'back_to_chat':
                        assert '\\d' in body['data'] and '\\w' in body['data'], 'cross-mode topic lost'
                    if label == 'summary_recall':
                        assert body['used_summary'], 'summary not used'
                        assert '松林计划' in body['data'] and '青绿色' in body['data'], 'summary lost preferences'
                state = (await client.get('/conversations/' + cid)).json()
                report['summary'] = state['conversation']['summary']
                report['rewritten_queries'] = [t['retrieval_query'] for t in state['data'] if t['retrieval_query']]
                other = (await client.post('/conversations')).json()['data']['id']
                report['isolated_conversation_id'] = other
                response = await client.post('/chat', json=dict(conversation_id=other,request_id=uuid4().hex,
                                                                user_input='请只回复：你好',mode='chat'))
                assert response.status_code == 200 and response.json()['history_turns'] == 0, 'new conversation not isolated'
                report['passed'] = True
    except Exception as exc:
        report['error_type'] = type(exc).__name__
        if isinstance(exc, AssertionError):
            report['error'] = str(exc)
    path = Path('output/live_conversations_report.json')
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('passed','conversation_id','error_type','error') if k in report}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(asyncio.run(check()))
