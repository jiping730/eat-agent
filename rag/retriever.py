"""Local vector retrieval with bounded metrics and trace correlation."""

from __future__ import annotations

import time

from core.logging_config import configure_logging, log_event
from core.observability import record_rag_retrieval, start_span
from rag.vector_store import get_or_create_vector_store


def get_retriever_with_score(score_threshold: float = 2.0):
    """Return a retriever that records hit rate, latency, and result count.

    Query text is intentionally excluded from logs, metric labels, and span
    attributes because it can contain personal or health information.
    """

    logger = configure_logging()

    def retrieve(query: str):
        started_at = time.perf_counter()
        document_count = 0
        with start_span(
            "rag.retrieve",
            {"rag.score_threshold": float(score_threshold)},
        ):
            try:
                vectorstore = get_or_create_vector_store()
                docs_with_scores = vectorstore.similarity_search_with_score(query, k=4)
                # FAISS returns L2 distance: lower values are more similar.
                filtered_docs = [doc for doc, score in docs_with_scores if score < score_threshold]
                document_count = len(filtered_docs)
                elapsed = time.perf_counter() - started_at
                record_rag_retrieval("success", bool(filtered_docs), elapsed, document_count)
                log_event(
                    logger,
                    20,
                    "rag_retrieval_completed",
                    status="success",
                    hit=bool(filtered_docs),
                    document_count=document_count,
                    duration_ms=round(elapsed * 1000, 2),
                )
                return filtered_docs
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
