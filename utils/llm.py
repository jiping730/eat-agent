from typing import Optional, List
from langchain.llms.base import LLM
from zhipuai import ZhipuAI
from config import settings

class CustomZhipuChat(LLM):
    def __init__(self):
        super().__init__()
        # 使用 object.__setattr__ 绕过 Pydantic 的字段验证
        object.__setattr__(self, 'client', ZhipuAI(api_key=settings.zhipuai_api_key))
        object.__setattr__(self, 'model', settings.llm_model)
        object.__setattr__(self, 'temperature', 0.7)

    @property
    def _llm_type(self) -> str:
        return "zhipuai"

    def _call(self, prompt: str, stop: Optional[List[str]] = None, **kwargs) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=self.temperature
        )
        return response.choices[0].message.content

def get_llm():
    return CustomZhipuChat()