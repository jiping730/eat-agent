"""Short-term and optional FAISS-backed long-term memory."""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from langchain_community.vectorstores import FAISS

from config import settings
from core.logging_config import configure_logging, log_event
from rag.embeddings import get_embeddings


logger = configure_logging(settings.log_level)


class MemoryManager:
    def __init__(self):
        self.short_term = []
        self.long_term_path = os.path.join(settings.memory_path, "long_term")
        self.long_term = None
        try:
            self.long_term = self._load_long_term()
        except Exception as exc:
            log_event(logger, 30, "long_term_memory_disabled", error_type=type(exc).__name__)

        self.meta_file = os.path.join(settings.memory_path, "meta.json")
        try:
            self._ensure_dir()
        except OSError as exc:
            log_event(logger, 30, "memory_meta_persistence_disabled", error_type=type(exc).__name__)

    def _ensure_dir(self):
        os.makedirs(settings.memory_path, exist_ok=True)
        if not os.path.exists(self.meta_file):
            with open(self.meta_file, "w", encoding="utf-8") as file:
                json.dump([], file)

    def _load_long_term(self):
        embeddings = get_embeddings()
        if os.path.exists(self.long_term_path):
            return FAISS.load_local(self.long_term_path, embeddings, allow_dangerous_deserialization=True)
        temp_texts = ["placeholder"]
        return FAISS.from_texts(temp_texts, embeddings)

    def save_long_term(self):
        if self.long_term is None:
            return
        os.makedirs(os.path.dirname(self.long_term_path), exist_ok=True)
        self.long_term.save_local(self.long_term_path)

    def add_interaction(self, user_input: str, agent_output: str, user_id: Optional[str] = None):
        self.short_term.append(
            {
                "input": user_input,
                "output": agent_output,
                "timestamp": datetime.now().isoformat(),
                "user_id": user_id,
            }
        )
        if len(self.short_term) > getattr(settings, "short_term_size", 10):
            self.short_term.pop(0)

        summary = f"用户问：{user_input} 执行：{agent_output}"
        if self.long_term is not None:
            try:
                self.long_term.add_texts([summary], metadatas=[{"type": "interaction", "user_id": user_id}])
                self.save_long_term()
            except Exception as exc:
                log_event(logger, 30, "long_term_memory_write_failed", error_type=type(exc).__name__)

    def retrieve_relevant_memories(self, query: str, user_id: Optional[str] = None, k: int = 5) -> List[str]:
        memories = []
        for mem in self.short_term:
            if any(word in mem["input"] for word in query.split()):
                memories.append(f"当前对话：{mem['input']} -> {mem['output']}")
        if self.long_term is not None:
            try:
                docs = self.long_term.similarity_search(query, k=k)
                for doc in docs:
                    memories.append(f"历史记忆：{doc.page_content}")
            except Exception as exc:
                log_event(logger, 30, "long_term_memory_retrieval_failed", error_type=type(exc).__name__)
        return memories[:k]

    def save_meta(self, user_input: str, agent_output: str, quality: float):
        try:
            with open(self.meta_file, "r", encoding="utf-8") as file:
                meta = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            meta = []
        meta.append(
            {
                "input": user_input,
                "output": agent_output,
                "quality": quality,
                "timestamp": datetime.now().isoformat(),
            }
        )
        meta = meta[-100:]
        try:
            with open(self.meta_file, "w", encoding="utf-8") as file:
                json.dump(meta, file, indent=2, ensure_ascii=False)
        except OSError as exc:
            log_event(logger, 30, "memory_meta_write_failed", error_type=type(exc).__name__)

    def get_meta_stats(self):
        try:
            with open(self.meta_file, "r", encoding="utf-8") as file:
                meta = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"count": 0, "avg_quality": 0}
        avg_quality = sum(item["quality"] for item in meta) / len(meta) if meta else 0
        return {"count": len(meta), "avg_quality": avg_quality}
