"""Short-term and optional FAISS-backed long-term memory."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from typing import Any, List, Optional

from langchain_community.vectorstores import FAISS

from config import settings
from core.logging_config import configure_logging, log_event
from rag.embeddings import get_embeddings

logger = configure_logging(settings.log_level)


class MemoryManager:
    def __init__(self, store: Any | None = None):
        self.store = store
        self.short_term: list[dict[str, Any]] = []
        self._lock = threading.RLock()
        self.long_term_path = os.path.join(settings.memory_path, "long_term")
        self.long_term = None
        try:
            self.long_term = self._load_long_term()
        except Exception as exc:
            log_event(logger, 30, "long_term_memory_disabled", error_type=type(exc).__name__)

        self.meta_file = os.path.join(settings.memory_path, "meta.json")
        self.governance_file = os.path.join(settings.memory_path, "governance.json")
        try:
            self._ensure_dir()
        except OSError as exc:
            log_event(logger, 30, "memory_meta_persistence_disabled", error_type=type(exc).__name__)

    def _ensure_dir(self):
        os.makedirs(settings.memory_path, exist_ok=True)
        if not os.path.exists(self.meta_file):
            with open(self.meta_file, "w", encoding="utf-8") as file:
                json.dump([], file)
        if self.store is None and not os.path.exists(self.governance_file):
            with open(self.governance_file, "w", encoding="utf-8") as file:
                json.dump({"consents": {}, "items": {}}, file)

    def set_store(self, store: Any) -> None:
        self.store = store

    def _load_governance(self) -> dict[str, Any]:
        try:
            with open(self.governance_file, "r", encoding="utf-8") as file:
                payload = json.load(file)
            if not isinstance(payload, dict):
                return {"consents": {}, "items": {}}
            payload.setdefault("consents", {})
            payload.setdefault("items", {})
            return payload
        except (FileNotFoundError, json.JSONDecodeError):
            return {"consents": {}, "items": {}}

    def _save_governance(self, payload: dict[str, Any]) -> None:
        with open(self.governance_file, "w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2, ensure_ascii=False)

    def has_consent(self, user_id: str | None, tenant_id: str | None = None) -> bool:
        if not user_id:
            return False
        if self.store is not None and hasattr(self.store, "get_memory_consent"):
            return bool(self.store.get_memory_consent(user_id, tenant_id))
        with self._lock:
            return bool(self._load_governance().get("consents", {}).get(user_id, False))

    def set_consent(self, user_id: str, granted: bool, tenant_id: str | None = None) -> bool:
        if not user_id or not user_id.strip():
            raise ValueError("user_id 不能为空")
        if self.store is not None and hasattr(self.store, "set_memory_consent"):
            result = bool(self.store.set_memory_consent(user_id, bool(granted), tenant_id))
            if not granted:
                self.short_term = [
                    item
                    for item in self.short_term
                    if not (item.get("user_id") == user_id and item.get("tenant_id") == tenant_id)
                ]
            return result
        with self._lock:
            payload = self._load_governance()
            payload["consents"][user_id] = bool(granted)
            if not granted:
                payload["items"].pop(user_id, None)
                self.short_term = [item for item in self.short_term if item.get("user_id") != user_id]
            self._save_governance(payload)
        return bool(granted)

    def export_user_memory(self, user_id: str, tenant_id: str | None = None) -> dict[str, Any]:
        if self.store is not None and hasattr(self.store, "export_memory"):
            return self.store.export_memory(user_id, tenant_id)
        with self._lock:
            payload = self._load_governance()
            return {
                "user_id": user_id,
                "consent": bool(payload["consents"].get(user_id, False)),
                "items": list(payload["items"].get(user_id, [])),
            }

    def delete_user_memory(
        self, user_id: str, *, revoke_consent: bool = True, tenant_id: str | None = None
    ) -> int:
        if self.store is not None and hasattr(self.store, "delete_memory"):
            deleted = int(
                self.store.delete_memory(user_id, revoke_consent=revoke_consent, tenant_id=tenant_id)
            )
            self.short_term = [
                item
                for item in self.short_term
                if not (item.get("user_id") == user_id and item.get("tenant_id") == tenant_id)
            ]
            return deleted
        with self._lock:
            payload = self._load_governance()
            count = len(payload["items"].get(user_id, []))
            payload["items"].pop(user_id, None)
            if revoke_consent:
                payload["consents"][user_id] = False
            self._save_governance(payload)
            self.short_term = [item for item in self.short_term if item.get("user_id") != user_id]
            return count

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

    def add_interaction(
        self,
        user_input: str,
        agent_output: str,
        user_id: Optional[str] = None,
        tenant_id: str | None = None,
    ):
        from core.safety_guard import SafetyGuard

        safe_input, _ = SafetyGuard.redact(user_input)
        safe_output, _ = SafetyGuard.redact(agent_output)
        self.short_term.append(
            {
                "input": safe_input,
                "output": safe_output,
                "timestamp": datetime.now().isoformat(),
                "user_id": user_id,
                "tenant_id": tenant_id,
            }
        )
        if len(self.short_term) > getattr(settings, "short_term_size", 10):
            self.short_term.pop(0)

        if not self.has_consent(user_id, tenant_id):
            return

        if self.store is not None and hasattr(self.store, "save_memory"):
            try:
                self.store.save_memory(
                    user_id=str(user_id),
                    user_input=safe_input,
                    assistant_output=safe_output,
                    tenant_id=tenant_id,
                )
            except Exception as exc:
                log_event(logger, 30, "governed_memory_write_failed", error_type=type(exc).__name__)
            return

        summary = f"用户问：{safe_input} 执行：{safe_output}"
        if self.long_term is not None:
            try:
                self.long_term.add_texts([summary], metadatas=[{"type": "interaction", "user_id": user_id}])
                self.save_long_term()
            except Exception as exc:
                log_event(logger, 30, "long_term_memory_write_failed", error_type=type(exc).__name__)

    def retrieve_relevant_memories(
        self, query: str, user_id: Optional[str] = None, k: int = 5, tenant_id: str | None = None
    ) -> List[str]:
        if user_id and not self.has_consent(user_id, tenant_id):
            return []
        memories = []
        for mem in self.short_term:
            if user_id and (mem.get("user_id") != user_id or mem.get("tenant_id") != tenant_id):
                continue
            if any(word in mem["input"] for word in query.split()):
                memories.append(f"当前对话：{mem['input']} -> {mem['output']}")
        if self.has_consent(user_id, tenant_id) and self.store is not None and hasattr(self.store, "list_memory"):
            try:
                for item in reversed(self.store.list_memory(str(user_id), limit=k, tenant_id=tenant_id)):
                    if any(word in item["input"] for word in query.split()):
                        memories.append(f"历史记忆：用户问：{item['input']} 执行：{item['output']}")
            except Exception as exc:
                log_event(logger, 30, "governed_memory_retrieval_failed", error_type=type(exc).__name__)
        elif self.has_consent(user_id, tenant_id) and self.long_term is not None:
            try:
                docs = self.long_term.similarity_search(query, k=k)
                for doc in docs:
                    if user_id and doc.metadata.get("user_id") != user_id:
                        continue
                    memories.append(f"历史记忆：{doc.page_content}")
            except Exception as exc:
                log_event(logger, 30, "long_term_memory_retrieval_failed", error_type=type(exc).__name__)
        return memories[:k]

    def save_meta(
        self,
        user_input: str,
        agent_output: str,
        quality: float,
        user_id: str | None = None,
        tenant_id: str | None = None,
    ):
        if user_id and not self.has_consent(user_id, tenant_id):
            return
        from core.safety_guard import SafetyGuard

        user_input, _ = SafetyGuard.redact(user_input)
        agent_output, _ = SafetyGuard.redact(agent_output)
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
