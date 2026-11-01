"""
依赖注入:一个类需要使用另一个对象时，不自己创建这个对象，而是由外部把这个对象传进来。
"""


from typing import Annotated
from fastapi import Depends, Request
from src.llm.llm_client import MultiLLMClient

def get_llm_dependency(request: Request) -> MultiLLMClient:
    # 从request.app.state获取llm_client
    return request.app.state.llm_client


LLMDep = Annotated[
    MultiLLMClient,
    Depends(get_llm_dependency),
]
