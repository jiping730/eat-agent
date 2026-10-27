"""Hybrid lexical/vector retrieval with provenance and access filtering."""

from __future__ import annotations

import math
import re
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from langchain_core.documents import Document

from config import settings
from core.contracts import RetrievalResponse, RetrievedDocument, SourceRef
from core.logging_config import configure_logging, log_event
from core.observability import record_rag_retrieval, start_span
from rag.ingestion import build_documents, load_active_documents
from rag.vector_store import get_or_create_vector_store

_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]", re.IGNORECASE)
_QUERY_SYNONYMS = {
    "卡路里": "热量",
    "卡路里表": "热量表",
    "减脂": "减肥",
    "减重": "减肥",
    "营养成分": "营养",
}


class _DefaultVectorLoader:
    """Sentinel that keeps the runtime-default loader monkeypatchable in tests."""


_DEFAULT_VECTOR_LOADER = _DefaultVectorLoader()


@dataclass(frozen=True)
class QueryRewrite:
    original: str
    normalized: str
    terms: tuple[str, ...]


def rewrite_query(query: str) -> QueryRewrite:
    """Apply deterministic, auditable query normalization before retrieval."""

    normalized = unicodedata.normalize("NFKC", query or "").strip().casefold()
    for source, target in _QUERY_SYNONYMS.items():
        normalized = normalized.replace(source, target)
    terms = tuple(dict.fromkeys(_tokens(normalized)))
    return QueryRewrite(original=query, normalized=normalized, terms=terms)


def _tokens(text: str) -> list[str]:
    return [match.group(0).casefold() for match in _TOKEN_RE.finditer(text)]


def _document_key(document: Document) -> str:
    metadata = getattr(document, "metadata", {}) or {}
    return str(metadata.get("chunk_id") or metadata.get("content_hash") or document.page_content)


def _allowed(document: Document, access_groups: set[str] | None) -> bool:
    if access_groups is None:
        return True
    metadata = getattr(document, "metadata", {}) or {}
    document_groups = set(metadata.get("access_groups") or ["public"])
    return bool(document_groups.intersection(access_groups))


def _lexical_rank(query_terms: tuple[str, ...], documents: Iterable[Document]) -> list[tuple[Document, float]]:
    docs = list(documents)
    if not query_terms or not docs:
        return []
    tokenized = [_tokens(document.page_content) for document in docs]
    document_frequency: dict[str, int] = {}
    for terms in tokenized:
        for term in set(terms):
            document_frequency[term] = document_frequency.get(term, 0) + 1
    total = len(docs)
    scored: list[tuple[Document, float]] = []
    for document, terms in zip(docs, tokenized):
        counts = {term: terms.count(term) for term in set(terms)}
        score = 0.0
        for term in query_terms:
            frequency = counts.get(term, 0)
            if not frequency:
                continue
            inverse_frequency = math.log((total + 1) / (document_frequency.get(term, 0) + 1)) + 1
            score += inverse_frequency * (frequency / (frequency + 1.2))
        if score > 0:
            scored.append((document, score))
    if not scored:
        return []
    maximum = max(score for _, score in scored)
    return [(document, score / maximum) for document, score in scored]


def rerank_documents(
    rewrite: QueryRewrite,
    candidates: Iterable[tuple[Document, float]],
) -> list[tuple[Document, float]]:
    """Apply a deterministic local reranker after multi-route recall.

    The small-platform default deliberately has no model or network dependency.
    It boosts query-term coverage, exact phrase matches, and title matches while
    preserving the lexical/vector score as the dominant signal.  The function
    is isolated so a BGE/Cohere reranker can replace it later without changing
    the ingestion or Tool Registry contracts.
    """

    query_terms = set(rewrite.terms)
    normalized_query = rewrite.normalized.replace(" ", "")
    reranked: list[tuple[Document, float]] = []
    for document, base_score in candidates:
        content = document.page_content.casefold()
        content_terms = set(_tokens(content))
        coverage = len(query_terms.intersection(content_terms)) / len(query_terms) if query_terms else 0.0
        phrase_boost = 0.08 if normalized_query and normalized_query in content.replace(" ", "") else 0.0
        title = str((getattr(document, "metadata", {}) or {}).get("title") or "")
        title_terms = set(_tokens(title.casefold()))
        title_boost = 0.04 if query_terms.intersection(title_terms) else 0.0
        score = min(1.0, float(base_score) * 0.72 + coverage * 0.24 + phrase_boost + title_boost)
        metadata = dict(getattr(document, "metadata", {}) or {})
        metadata.update(
            {
                "retrieval_score": round(score, 6),
                "rerank_score": round(score, 6),
                "rerank_method": "deterministic_coverage",
            }
        )
        reranked.append((Document(page_content=document.page_content, metadata=metadata), score))
    reranked.sort(key=lambda item: item[1], reverse=True)
    return reranked


class HybridRetriever:
    """Combine deterministic lexical recall with the existing FAISS index."""

    def __init__(
        self,
        *,
        source_dir: str | None = None,
        index_dir: str | None = None,
        vector_loader: Callable[[], Any] | None | _DefaultVectorLoader = _DEFAULT_VECTOR_LOADER,
        score_threshold: float = 2.0,
        top_k: int = 4,
        access_groups: set[str] | None = None,
    ) -> None:
        self.source_dir = source_dir or settings.documents_path
        self.index_dir = index_dir or settings.vector_store_path
        if isinstance(vector_loader, _DefaultVectorLoader):
            self.vector_loader: Callable[[], Any] | None = get_or_create_vector_store
        else:
            self.vector_loader = vector_loader
        self.score_threshold = score_threshold
        self.top_k = max(1, top_k)
        self.access_groups = access_groups

    def _corpus(self) -> list[Document]:
        published = load_active_documents(self.index_dir)
        return published or build_documents(self.source_dir)

    def _vector_rank(self, query: str) -> list[tuple[Document, float]]:
        if self.vector_loader is None:
            return []
        index_path = Path(self.index_dir) / "index.faiss"
        if not index_path.exists() and self.vector_loader is get_or_create_vector_store:
            return []
        try:
            vectorstore = self.vector_loader()
            docs_with_scores = vectorstore.similarity_search_with_score(query, k=max(self.top_k * 2, 8))
        except Exception:
            return []
        ranked: list[tuple[Document, float]] = []
        for document, distance in docs_with_scores:
            if distance >= self.score_threshold:
                continue
            relevance = 1 / (1 + max(float(distance), 0.0))
            ranked.append((document, relevance))
        return ranked

    def retrieve(self, query: str) -> list[Document]:
        rewrite = rewrite_query(query)
        corpus = [document for document in self._corpus() if _allowed(document, self.access_groups)]
        lexical = dict(
            (_document_key(document), (document, score)) for document, score in _lexical_rank(rewrite.terms, corpus)
        )
        vector = dict(
            (_document_key(document), (document, score))
            for document, score in self._vector_rank(query)
            if _allowed(document, self.access_groups)
        )

        merged: list[tuple[Document, float]] = []
        for key in set(lexical) | set(vector):
            lexical_item = lexical.get(key)
            vector_item = vector.get(key)
            candidate = lexical_item if lexical_item is not None else vector_item
            if candidate is None:
                continue
            document, score = candidate
            if lexical_item and vector_item:
                score = lexical_item[1] * 0.6 + vector_item[1] * 0.4
                method = "hybrid"
            elif lexical_item:
                method = "bm25"
            else:
                method = "vector"
            metadata = dict(getattr(document, "metadata", {}) or {})
            metadata.update(
                {
                    "retrieval_score": round(float(score), 6),
                    "retrieval_method": method,
                    "query_rewrite": rewrite.normalized,
                }
            )
            merged.append((Document(page_content=document.page_content, metadata=metadata), float(score)))
        reranked = rerank_documents(rewrite, merged)
        return [document for document, _ in reranked[: self.top_k]]


def get_retriever_with_score(
    score_threshold: float = 2.0,
    *,
    top_k: int = 4,
    access_groups: set[str] | None = None,
):
    """Return a retriever that records hit rate, latency, and result count."""

    logger = configure_logging()
    retriever = HybridRetriever(
        score_threshold=score_threshold,
        top_k=top_k,
        access_groups=access_groups,
    )

    def retrieve(query: str) -> list[Document]:
        started_at = time.perf_counter()
        document_count = 0
        with start_span("rag.retrieve", {"rag.score_threshold": float(score_threshold)}):
            try:
                documents = retriever.retrieve(query)
                document_count = len(documents)
                elapsed = time.perf_counter() - started_at
                record_rag_retrieval("success", bool(documents), elapsed, document_count)
                log_event(
                    logger,
                    20,
                    "rag_retrieval_completed",
                    status="success",
                    hit=bool(documents),
                    document_count=document_count,
                    duration_ms=round(elapsed * 1000, 2),
                )
                return documents
            except Exception as exc:
                elapsed = time.perf_counter() - started_at
                record_rag_retrieval("error", False, elapsed, document_count)
                log_event(
                    logger,
                    30,
                    "rag_retrieval_failed",
                    error_type=type(exc).__name__,
                    duration_ms=round(elapsed * 1000, 2),
                )
                raise

    return retrieve


def retrieve_with_contract(
    query: str,
    *,
    score_threshold: float = 2.0,
    top_k: int = 4,
    access_groups: set[str] | None = None,
) -> RetrievalResponse:
    """Return the P1 contract while retaining the legacy text adapter."""

    documents = get_retriever_with_score(
        score_threshold=score_threshold,
        top_k=top_k,
        access_groups=access_groups,
    )(query)
    retrieved: list[RetrievedDocument] = []
    sources: list[SourceRef] = []
    for document in documents:
        metadata = document.metadata or {}
        source = SourceRef(
            type=str(metadata.get("type") or "knowledge_base"),
            source=str(metadata.get("source") or "local_knowledge_base"),
            title=metadata.get("title"),
            document_id=metadata.get("document_id"),
            version=metadata.get("version"),
            chunk_id=metadata.get("chunk_id"),
            score=metadata.get("retrieval_score"),
        )
        sources.append(source)
        retrieved.append(
            RetrievedDocument(
                content=document.page_content,
                source=source,
                score=metadata.get("retrieval_score"),
                metadata=metadata,
            )
        )
    return RetrievalResponse(
        status="success" if retrieved else "no_results",
        documents=retrieved,
        sources=sources,
    )
