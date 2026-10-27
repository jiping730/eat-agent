import time
from typing import Optional, List
from langchain.llms.base import LLM
from zhipuai import ZhipuAI
from config import settings
from core.observability import record_llm_call

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
        started_at = time.perf_counter()
        if not settings.zhipuai_api_key:
            record_llm_call("fallback", time.perf_counter() - started_at)
            raise RuntimeError("ZHIPUAI_API_KEY 未配置")
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.temperature,
                timeout=30.0  # 设置超时，避免卡死
            )
            answer = response.choices[0].message.content
            record_llm_call("success", time.perf_counter() - started_at)
            return answer
        except Exception as exc:
            record_llm_call("failure", time.perf_counter() - started_at)
            raise RuntimeError("LLM 服务暂时不可用") from exc

def get_llm():
    return CustomZhipuChat()
