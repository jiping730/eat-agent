import time
from langchain.callbacks.base import BaseCallbackHandler
from typing import Dict, Any

class PerformanceCallbackHandler(BaseCallbackHandler):
    def __init__(self):
        self.total_retrievals = 0
        self.start_time = None
        self.end_time = None

    def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs) -> None:
        tool_name = serialized.get("name")
        if tool_name == "retrieval_tool":   # 与工具名称一致
            self.total_retrievals += 1

    def on_chain_start(self, serialized: Dict[str, Any], inputs: Dict[str, Any], **kwargs) -> None:
        self.start_time = time.time()

    def on_chain_end(self, outputs: Dict[str, Any], **kwargs) -> None:
        self.end_time = time.time()

    def get_stats(self):
        return {
            "response_time": self.end_time - self.start_time if self.start_time and self.end_time else None,
            "retrieval_count": self.total_retrievals
        }