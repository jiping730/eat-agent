"""Small-platform knowledge-base governance and publishing service.

The service owns document lifecycle state and delegates corpus construction to
the existing deterministic RAG ingestion pipeline.  It intentionally keeps
index builds synchronous for the small-platform target while persisting build
progress so the API and browser admin page have an observable status contract.
"""

from __future__ import annotations

import hashlib
import re
import threading
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select

from config import settings
from core.persistence import (
    KnowledgeBuildRecord,
    KnowledgeDocumentRecord,
    KnowledgeDocumentVersionRecord,
    KnowledgeRetrievalEventRecord,
    ConversationStore,
    utc_now,
)
from rag.ingestion import active_version, ingest_document_entries, publish_version, rollback_version
from rag.retriever import retrieve_with_contract

_SOURCE_NAME_RE = re.compile(r"^[^\\/:*?\"<>|\x00]+$")
_ALLOWED_SUFFIXES = {".md", ".txt"}
_DOCUMENT_STATUSES = {"draft", "approved", "rejected", "published", "unpublished"}


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _hash_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _groups(values: Iterable[str] | None) -> list[str]:
    normalized = {str(value).strip() for value in (values or ["public"]) if str(value).strip()}
    return sorted(normalized or {"public"})


class KnowledgeBaseService:
    """Manage reviewed documents and atomically publish their RAG corpus."""

    _build_lock = threading.Lock()

    def __init__(self, store: ConversationStore, *, index_dir: str | None = None) -> None:
        self.store = store
        self.index_dir = Path(index_dir or settings.vector_store_path)

    @staticmethod
    def validate_source_name(source_name: str) -> str:
        value = Path(str(source_name).strip()).name
        if not value or value != str(source_name).strip() or not _SOURCE_NAME_RE.fullmatch(value):
            raise ValueError("文档文件名不合法")
        if Path(value).suffix.lower() not in _ALLOWED_SUFFIXES:
            raise ValueError("当前仅支持 .txt 和 .md 文档")
        return value

    @staticmethod
    def _document_payload(document: KnowledgeDocumentRecord, versions: list[KnowledgeDocumentVersionRecord]) -> dict[str, Any]:
        return {
            "id": document.id,
            "source_name": document.source_name,
            "title": document.title,
            "status": document.status,
            "latest_version": document.latest_version,
            "published_version": document.published_version,
            "access_groups": list(document.access_groups or ["public"]),
            "created_by": document.created_by,
            "updated_by": document.updated_by,
            "reviewed_by": document.reviewed_by,
            "review_note": document.review_note,
            "created_at": _iso(document.created_at),
            "updated_at": _iso(document.updated_at),
            "versions": [
                {
                    "version": item.version,
                    "content_hash": item.content_hash,
                    "created_by": item.created_by,
                    "created_at": _iso(item.created_at),
                    "content": item.content,
                }
                for item in versions
            ],
        }

    @staticmethod
    def _build_payload(build: KnowledgeBuildRecord) -> dict[str, Any]:
        return {
            "id": build.id,
            "index_version": build.index_version,
            "status": build.status,
            "phase": build.phase,
            "progress": build.progress,
            "document_count": build.document_count,
            "chunk_count": build.chunk_count,
            "error": build.error,
            "initiated_by": build.initiated_by,
            "started_at": _iso(build.started_at),
            "finished_at": _iso(build.finished_at),
        }

    def upload_document(
        self,
        *,
        source_name: str,
        content: str,
        actor: str,
        title: str | None = None,
        access_groups: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        source_name = self.validate_source_name(source_name)
        if not isinstance(content, str) or not content.strip():
            raise ValueError("文档内容不能为空")
        if len(content.encode("utf-8")) > settings.knowledge_max_document_bytes:
            raise ValueError("文档超过大小限制")
        normalized_title = (title or Path(source_name).stem).strip()[:200]
        if not normalized_title:
            raise ValueError("文档标题不能为空")
        normalized_groups = _groups(access_groups)
        with self.store.session_factory.begin() as session:
            document = session.scalar(
                select(KnowledgeDocumentRecord).where(KnowledgeDocumentRecord.source_name == source_name)
            )
            now = utc_now()
            if document is None:
                document = KnowledgeDocumentRecord(
                    id=str(uuid.uuid4()),
                    source_name=source_name,
                    title=normalized_title,
                    status="draft",
                    latest_version=1,
                    published_version=None,
                    access_groups=normalized_groups,
                    created_by=actor,
                    updated_by=actor,
                    created_at=now,
                    updated_at=now,
                )
                session.add(document)
                version = 1
            else:
                version = document.latest_version + 1
                document.latest_version = version
                document.title = normalized_title
                document.status = "draft"
                document.access_groups = normalized_groups
                document.updated_by = actor
                document.reviewed_by = None
                document.review_note = None
                document.updated_at = now
            session.flush()
            session.add(
                KnowledgeDocumentVersionRecord(
                    document_id=document.id,
                    version=version,
                    content=content,
                    content_hash=_hash_content(content),
                    created_by=actor,
                    created_at=now,
                )
            )
            document_id = document.id
        return self.get_document(document_id)

    def list_documents(self, *, status: str | None = None) -> list[dict[str, Any]]:
        if status is not None and status not in _DOCUMENT_STATUSES:
            raise ValueError("文档状态不合法")
        with self.store.session_factory() as session:
            query = select(KnowledgeDocumentRecord).order_by(KnowledgeDocumentRecord.updated_at.desc())
            if status:
                query = query.where(KnowledgeDocumentRecord.status == status)
            documents = session.scalars(query).all()
            return [self._document_payload(document, []) for document in documents]

    def get_document(self, document_id: str) -> dict[str, Any]:
        with self.store.session_factory() as session:
            document = session.get(KnowledgeDocumentRecord, document_id)
            if document is None:
                raise KeyError("知识文档不存在")
            versions = session.scalars(
                select(KnowledgeDocumentVersionRecord)
                .where(KnowledgeDocumentVersionRecord.document_id == document_id)
                .order_by(KnowledgeDocumentVersionRecord.version.desc())
            ).all()
            return self._document_payload(document, list(versions))

    def review_document(self, document_id: str, *, actor: str, approved: bool, note: str | None = None) -> dict[str, Any]:
        with self.store.session_factory.begin() as session:
            document = session.get(KnowledgeDocumentRecord, document_id)
            if document is None:
                raise KeyError("知识文档不存在")
            if document.status not in {"draft", "rejected", "approved"}:
                raise ValueError("当前文档状态不可审核")
            document.status = "approved" if approved else "rejected"
            document.reviewed_by = actor
            document.review_note = (note or "").strip()[:2_000] or None
            document.updated_by = actor
            document.updated_at = utc_now()
        return self.get_document(document_id)

    def _release_entries(self) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        with self.store.session_factory() as session:
            documents = session.scalars(select(KnowledgeDocumentRecord)).all()
            for document in documents:
                if document.status == "unpublished":
                    continue
                version_number = document.latest_version if document.status == "approved" else document.published_version
                if version_number is None:
                    continue
                version = session.scalar(
                    select(KnowledgeDocumentVersionRecord).where(
                        KnowledgeDocumentVersionRecord.document_id == document.id,
                        KnowledgeDocumentVersionRecord.version == version_number,
                    )
                )
                if version is None:
                    continue
                entries.append(
                    {
                        "content": version.content,
                        "source": document.source_name,
                        "title": document.title,
                        "document_id": document.id,
                        "access_groups": list(document.access_groups or ["public"]),
                    }
                )
        return entries

    def _set_build(self, build_id: str, **values: Any) -> dict[str, Any]:
        with self.store.session_factory.begin() as session:
            build = session.get(KnowledgeBuildRecord, build_id)
            if build is None:
                raise KeyError("索引构建任务不存在")
            for key, value in values.items():
                setattr(build, key, value)
            return self._build_payload(build)

    def build_index(self, *, actor: str) -> dict[str, Any]:
        """Build and publish one complete corpus synchronously with progress."""

        with self._build_lock:
            build_id = str(uuid.uuid4())
            index_version = f"kb-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{build_id[:8]}"
            with self.store.session_factory.begin() as session:
                session.add(
                    KnowledgeBuildRecord(
                        id=build_id,
                        index_version=index_version,
                        status="building",
                        phase="preparing",
                        progress=5,
                        initiated_by=actor,
                        started_at=utc_now(),
                    )
                )
            try:
                entries = self._release_entries()
                self._set_build(
                    build_id,
                    phase="collecting",
                    progress=25,
                    document_count=len(entries),
                )
                manifest = ingest_document_entries(
                    self.index_dir,
                    entries,
                    version=index_version,
                    publish=False,
                )
                self._set_build(
                    build_id,
                    phase="publishing",
                    progress=85,
                    document_count=int(manifest.get("document_count", len(entries))),
                    chunk_count=int(manifest.get("chunk_count", 0)),
                )
                publish_version(self.index_dir, index_version)
                with self.store.session_factory.begin() as session:
                    approved = session.scalars(
                        select(KnowledgeDocumentRecord).where(KnowledgeDocumentRecord.status == "approved")
                    ).all()
                    for document in approved:
                        document.status = "published"
                        document.published_version = document.latest_version
                        document.updated_at = utc_now()
                    build = session.get(KnowledgeBuildRecord, build_id)
                    if build is not None:
                        build.status = "published"
                        build.phase = "completed"
                        build.progress = 100
                        build.finished_at = utc_now()
                return self.get_build(build_id)
            except Exception as exc:
                self._set_build(
                    build_id,
                    status="failed",
                    phase="failed",
                    progress=100,
                    error=str(exc)[:2_000],
                    finished_at=utc_now(),
                )
                raise

    def get_build(self, build_id: str) -> dict[str, Any]:
        with self.store.session_factory() as session:
            build = session.get(KnowledgeBuildRecord, build_id)
            if build is None:
                raise KeyError("索引构建任务不存在")
            return self._build_payload(build)

    def list_builds(self, *, limit: int = 20) -> list[dict[str, Any]]:
        with self.store.session_factory() as session:
            builds = session.scalars(
                select(KnowledgeBuildRecord)
                .order_by(KnowledgeBuildRecord.started_at.desc())
                .limit(max(1, min(limit, 100)))
            ).all()
            return [self._build_payload(build) for build in builds]

    def publish_document(self, document_id: str, *, actor: str) -> dict[str, Any]:
        document = self.get_document(document_id)
        if document["status"] != "approved":
            raise ValueError("文档必须审核通过后才能发布")
        build = self.build_index(actor=actor)
        return {"document": self.get_document(document_id), "build": build}

    def unpublish_document(self, document_id: str, *, actor: str) -> dict[str, Any]:
        with self.store.session_factory.begin() as session:
            document = session.get(KnowledgeDocumentRecord, document_id)
            if document is None:
                raise KeyError("知识文档不存在")
            if document.status != "published":
                raise ValueError("只有已发布文档才能下线")
            document.status = "unpublished"
            document.updated_by = actor
            document.updated_at = utc_now()
        try:
            build = self.build_index(actor=actor)
        except Exception:
            with self.store.session_factory.begin() as session:
                document = session.get(KnowledgeDocumentRecord, document_id)
                if document is not None:
                    document.status = "published"
                    document.updated_by = actor
                    document.updated_at = utc_now()
            raise
        return {"document": self.get_document(document_id), "build": build}

    def rollback(self, target: str, *, actor: str) -> dict[str, Any]:
        with self.store.session_factory() as session:
            build = session.get(KnowledgeBuildRecord, target)
            if build is None:
                build = session.scalar(select(KnowledgeBuildRecord).where(KnowledgeBuildRecord.index_version == target))
            if build is None or build.status == "failed":
                raise KeyError("可回滚的索引版本不存在")
            index_version = build.index_version
        rollback_version(self.index_dir, index_version)
        with self.store.session_factory.begin() as session:
            builds = session.scalars(select(KnowledgeBuildRecord)).all()
            for item in builds:
                if item.status == "published":
                    item.status = "rolled_back"
                if item.index_version == index_version:
                    item.status = "published"
        return {"active_version": active_version(self.index_dir), "rolled_back_to": index_version, "actor": actor}

    def retrieval_test(
        self,
        query: str,
        *,
        actor: str,
        top_k: int = 4,
        access_groups: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        if not query.strip():
            raise ValueError("检索问题不能为空")
        groups = _groups(access_groups)
        response = retrieve_with_contract(
            query,
            top_k=max(1, min(top_k, 10)),
            access_groups=set(groups),
            index_dir=str(self.index_dir),
        )
        document_ids = [source.document_id for source in response.sources if source.document_id]
        with self.store.session_factory.begin() as session:
            session.add(
                KnowledgeRetrievalEventRecord(
                    query=query[:2_000],
                    access_groups=groups,
                    result_count=len(response.documents),
                    result_document_ids=document_ids,
                    initiated_by=actor,
                    created_at=utc_now(),
                )
            )
        return {
            "active_version": active_version(self.index_dir),
            "status": response.status,
            "documents": [item.model_dump() for item in response.documents],
            "sources": [item.model_dump() for item in response.sources],
        }

    def analytics(self) -> dict[str, Any]:
        with self.store.session_factory() as session:
            events = session.scalars(
                select(KnowledgeRetrievalEventRecord).order_by(KnowledgeRetrievalEventRecord.created_at.desc()).limit(10_000)
            ).all()
        total = len(events)
        hits = sum(1 for event in events if event.result_count > 0)
        source_counter: Counter[str] = Counter()
        for event in events:
            source_counter.update(str(item) for item in (event.result_document_ids or []))
        return {
            "active_version": active_version(self.index_dir),
            "total_queries": total,
            "hit_queries": hits,
            "hit_rate": round(hits / total, 4) if total else 0.0,
            "top_document_ids": [{"document_id": key, "hits": value} for key, value in source_counter.most_common(10)],
        }
