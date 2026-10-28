"""User-owned knowledge helpers for the small-platform personal scope."""

from __future__ import annotations

from typing import Any

from core.knowledge_base import KnowledgeBaseService
from core.persistence import ConversationStore


class PersonalKnowledgeService:
    """Thin user-facing facade over the existing knowledge lifecycle service.

    Personal documents skip administrator review, but still use the same
    immutable versions, deterministic ingestion, atomic index publishing and
    retrieval contracts as tenant documents.
    """

    _scope = "personal"
    _access_groups = ("personal",)

    def __init__(self, store: ConversationStore, *, knowledge_service: KnowledgeBaseService | None = None) -> None:
        self.store = store
        self.knowledge = knowledge_service or KnowledgeBaseService(store)

    def list_documents(self, *, user_id: str, tenant_id: str) -> list[dict[str, Any]]:
        return self.knowledge.list_documents(
            tenant_id=tenant_id,
            scope=self._scope,
            owner_user_id=user_id,
        )

    def has_documents(self, *, user_id: str, tenant_id: str) -> bool:
        return bool(self.list_documents(user_id=user_id, tenant_id=tenant_id))

    def import_text(
        self,
        *,
        user_id: str,
        tenant_id: str,
        source_name: str,
        content: str,
        title: str | None = None,
    ) -> dict[str, Any]:
        document = self.knowledge.upload_document(
            source_name=source_name,
            content=content,
            title=title,
            access_groups=self._access_groups,
            actor=user_id,
            tenant_id=tenant_id,
            scope=self._scope,
            owner_user_id=user_id,
            publish_immediately=True,
        )
        build = self.knowledge.build_index(
            actor=user_id,
            tenant_id=tenant_id,
            scope=self._scope,
            owner_user_id=user_id,
        )
        document = self.knowledge.get_document(
            document["id"],
            tenant_id,
            scope=self._scope,
            owner_user_id=user_id,
        )
        return {"document": document, "build": build}

    def delete_document(self, *, user_id: str, tenant_id: str, document_id: str) -> dict[str, Any]:
        return self.knowledge.delete_personal_document(
            document_id,
            actor=user_id,
            tenant_id=tenant_id,
            owner_user_id=user_id,
        )

    def retrieval_test(
        self,
        *,
        user_id: str,
        tenant_id: str,
        query: str,
        top_k: int = 4,
    ) -> dict[str, Any]:
        return self.knowledge.retrieval_test(
            query,
            actor=user_id,
            top_k=top_k,
            access_groups=self._access_groups,
            tenant_id=tenant_id,
            scope=self._scope,
            owner_user_id=user_id,
        )

    def index_status(self, *, user_id: str, tenant_id: str) -> dict[str, Any]:
        builds = self.knowledge.list_builds(
            limit=1,
            tenant_id=tenant_id,
            scope=self._scope,
            owner_user_id=user_id,
        )
        active = builds[0] if builds else None
        return {
            "scope": self._scope,
            "tenant_id": tenant_id,
            "owner_user_id": user_id,
            "active_version": active["index_version"] if active and active["status"] == "published" else None,
            "last_build": active,
        }
