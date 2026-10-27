"""Versioned, deterministic ingestion for the small-platform knowledge base."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from langchain_core.documents import Document

_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def clean_text(text: str) -> str:
    """Normalize text without changing the meaning of Chinese content."""

    text = text.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
    blocks: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in block.split("\n")]
        normalized = "\n".join(line for line in lines if line).strip()
        if normalized:
            blocks.append(normalized)
    return "\n\n".join(blocks)


def _dedupe_key(text: str) -> str:
    return re.sub(r"[\W_]+", "", text.casefold(), flags=re.UNICODE)


def split_text(text: str, *, chunk_size: int = 500, chunk_overlap: int = 50) -> list[str]:
    """Split paragraphs and long lines deterministically for reproducible indexes."""

    if chunk_size <= 0 or chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_size 必须大于 0，chunk_overlap 必须小于 chunk_size")
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", text) if item.strip()]
    chunks: list[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= chunk_size:
            chunks.append(paragraph)
            continue
        start = 0
        while start < len(paragraph):
            end = min(len(paragraph), start + chunk_size)
            chunks.append(paragraph[start:end].strip())
            if end == len(paragraph):
                break
            start = end - chunk_overlap
    return [chunk for chunk in chunks if chunk]


def _version(value: str | None) -> str:
    candidate = value or datetime.now(timezone.utc).strftime("v%Y%m%dT%H%M%SZ")
    if not _VERSION_RE.fullmatch(candidate):
        raise ValueError("version 只能包含字母、数字、点、下划线和短横线")
    return candidate


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _normalize_access_groups(access_groups: Iterable[str] | None) -> list[str]:
    groups = {str(group).strip() for group in (access_groups or ["public"]) if str(group).strip()}
    return sorted(groups or {"public"})


def build_documents(
    source_dir: str | os.PathLike[str],
    version: str = "legacy",
    *,
    access_groups: Iterable[str] | None = None,
) -> list[Document]:
    """Read text documents and return cleaned, deduplicated chunks."""

    root = Path(source_dir)
    if not root.exists():
        return []
    seen_chunks: set[str] = set()
    normalized_access_groups = _normalize_access_groups(access_groups)
    documents: list[Document] = []
    for path in sorted(root.rglob("*.txt")):
        if not path.is_file():
            continue
        text = clean_text(path.read_text(encoding="utf-8"))
        if not text:
            continue
        relative_path = path.relative_to(root).as_posix()
        document_id = _hash(relative_path)
        content_hash = _hash(text)
        for index, chunk in enumerate(split_text(text)):
            dedupe_key = _dedupe_key(chunk)
            if not dedupe_key or dedupe_key in seen_chunks:
                continue
            seen_chunks.add(dedupe_key)
            documents.append(
                Document(
                    page_content=chunk,
                    metadata={
                        "type": "knowledge_base",
                        "source": relative_path,
                        "title": path.stem,
                        "document_id": document_id,
                        "version": version,
                        "chunk_id": f"{document_id}:{index}",
                        "content_hash": content_hash,
                        "access_groups": normalized_access_groups,
                    },
                )
            )
    return documents


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _manifest(version: str, source_dir: str, documents: Iterable[Document]) -> dict[str, Any]:
    docs = list(documents)
    document_ids = {str(doc.metadata.get("document_id")) for doc in docs}
    return {
        "version": version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_dir": Path(source_dir).name,
        "document_count": len(document_ids),
        "chunk_count": len(docs),
        "backend": "lexical",
    }


def publish_version(index_dir: str | os.PathLike[str], version: str) -> None:
    """Atomically switch the active corpus pointer to an existing version."""

    root = Path(index_dir)
    version_dir = root / "versions" / version
    if not (version_dir / "corpus.json").is_file() or not (version_dir / "manifest.json").is_file():
        raise FileNotFoundError(f"知识库版本不存在或不完整：{version}")
    _write_json_atomic(root / "current.json", {"version": version})


def ingest_documents(
    source_dir: str | os.PathLike[str],
    index_dir: str | os.PathLike[str],
    *,
    version: str | None = None,
    publish: bool = True,
    access_groups: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Build a versioned corpus and optionally publish it atomically."""

    resolved_version = _version(version)
    root = Path(index_dir)
    versions_dir = root / "versions"
    versions_dir.mkdir(parents=True, exist_ok=True)
    version_dir = versions_dir / resolved_version
    if version_dir.exists():
        raise FileExistsError(f"知识库版本已存在：{resolved_version}")

    documents = build_documents(source_dir, resolved_version, access_groups=access_groups)
    manifest = _manifest(resolved_version, str(source_dir), documents)
    corpus = {
        "version": resolved_version,
        "documents": [{"page_content": document.page_content, "metadata": document.metadata} for document in documents],
    }
    temporary_dir = Path(tempfile.mkdtemp(prefix=f".{resolved_version}.", dir=versions_dir))
    try:
        _write_json_atomic(temporary_dir / "manifest.json", manifest)
        _write_json_atomic(temporary_dir / "corpus.json", corpus)
        os.replace(temporary_dir, version_dir)
    except BaseException:
        if temporary_dir.exists():
            for child in temporary_dir.iterdir():
                child.unlink()
            temporary_dir.rmdir()
        raise
    if publish:
        publish_version(root, resolved_version)
    return manifest


def rollback_version(index_dir: str | os.PathLike[str], version: str) -> None:
    """Switch the active pointer to a previously ingested version."""

    publish_version(index_dir, _version(version))


def active_version(index_dir: str | os.PathLike[str]) -> str | None:
    current_path = Path(index_dir) / "current.json"
    if not current_path.is_file():
        return None
    payload = json.loads(current_path.read_text(encoding="utf-8"))
    value = payload.get("version") if isinstance(payload, dict) else None
    return str(value) if value else None


def load_active_documents(index_dir: str | os.PathLike[str]) -> list[Document]:
    """Load the atomically published corpus, returning an empty list if absent."""

    version = active_version(index_dir)
    if not version:
        return []
    corpus_path = Path(index_dir) / "versions" / version / "corpus.json"
    if not corpus_path.is_file():
        return []
    payload = json.loads(corpus_path.read_text(encoding="utf-8"))
    raw_documents = payload.get("documents", []) if isinstance(payload, dict) else []
    return [
        Document(page_content=str(item["page_content"]), metadata=dict(item.get("metadata", {})))
        for item in raw_documents
        if isinstance(item, dict) and item.get("page_content")
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="构建并发布小型平台知识库版本")
    parser.add_argument("--source", required=True, help="文本知识库目录")
    parser.add_argument("--index", required=True, help="版本化索引目录")
    parser.add_argument("--version", default=None, help="版本号，默认使用 UTC 时间")
    parser.add_argument(
        "--access-group",
        action="append",
        dest="access_groups",
        help="文档访问组，可重复指定；默认 public",
    )
    parser.add_argument("--no-publish", action="store_true", help="只构建版本，不切换 current.json")
    args = parser.parse_args()
    print(
        json.dumps(
            ingest_documents(
                args.source,
                args.index,
                version=args.version,
                publish=not args.no_publish,
                access_groups=args.access_groups,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
