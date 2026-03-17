import os
import json
from typing import List, Dict, Any, Optional
from datetime import datetime
from langchain_community.vectorstores import FAISS
from rag.embeddings import get_embeddings
from config import settings

class MemoryManager:
    def __init__(self):
        self.short_term = []
        # 长期记忆向量库路径
        self.long_term_path = os.path.join(settings.memory_path, "long_term")
        self.long_term = self._load_long_term()
        # 元记忆文件
        self.meta_file = os.path.join(settings.memory_path, "meta.json")
        self._ensure_dir()

    def _ensure_dir(self):
        """确保记忆目录存在"""
        os.makedirs(settings.memory_path, exist_ok=True)
        if not os.path.exists(self.meta_file):
            with open(self.meta_file, "w", encoding="utf-8") as f:
                json.dump([], f)

    def _load_long_term(self):
        embeddings = get_embeddings()
        if os.path.exists(self.long_term_path):
            return FAISS.load_local(self.long_term_path, embeddings, allow_dangerous_deserialization=True)
        else:
            # 创建临时占位
            temp_texts = ["placeholder"]
            vectorstore = FAISS.from_texts(temp_texts, embeddings)
            return vectorstore

    def save_long_term(self):
        """持久化长期记忆"""
        os.makedirs(os.path.dirname(self.long_term_path), exist_ok=True)
        self.long_term.save_local(self.long_term_path)

    def add_interaction(self, user_input: str, agent_output: str, user_id: Optional[str] = None):
        # 短期记忆
        self.short_term.append({
            "input": user_input,
            "output": agent_output,
            "timestamp": datetime.now().isoformat(),
            "user_id": user_id
        })
        if len(self.short_term) > getattr(settings, 'short_term_size', 10):
            self.short_term.pop(0)

        # 长期记忆
        summary = f"用户问：{user_input} 助手答：{agent_output}"
        self.long_term.add_texts([summary], metadatas=[{"type": "interaction", "user_id": user_id}])
        self.save_long_term()

    def retrieve_relevant_memories(self, query: str, user_id: Optional[str] = None, k: int = 5) -> List[str]:
        memories = []
        # 短期记忆关键词匹配
        for mem in self.short_term:
            if any(word in mem["input"] for word in query.split()):
                memories.append(f"近期对话：{mem['input']} → {mem['output']}")
        # 长期记忆检索
        docs = self.long_term.similarity_search(query, k=k)
        for doc in docs:
            memories.append(f"历史记忆：{doc.page_content}")
        return memories[:k]

    def save_meta(self, user_input: str, agent_output: str, quality: float):
        """保存元记忆"""
        try:
            with open(self.meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            meta = []
        meta.append({
            "input": user_input,
            "output": agent_output,
            "quality": quality,
            "timestamp": datetime.now().isoformat()
        })
        # 保留最近 100 条
        meta = meta[-100:]
        with open(self.meta_file, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

    def get_meta_stats(self):
        try:
            with open(self.meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"count": 0, "avg_quality": 0}
        avg_quality = sum(m["quality"] for m in meta) / len(meta) if meta else 0
        return {"count": len(meta), "avg_quality": avg_quality}