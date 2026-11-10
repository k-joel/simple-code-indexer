"""get_status embedding progress and semantic-search readiness."""

from __future__ import annotations

from pathlib import Path

import pytest

from simple_code_indexer import db, embed, server, vector_store
from simple_code_indexer.config import IGNORE_DIRS, Settings
from simple_code_indexer.errors import EmbedError
from simple_code_indexer.models import Chunk, FileRecord, VectorHit
from simple_code_indexer.registry import get_registry


def _settings(workspace: Path) -> Settings:
    registry = get_registry()
    return Settings(
        workspace_root=workspace,
        index_db_path=workspace / ".simple-ci" / "index.db",
        qdrant_url="http://localhost:6333",
        qdrant_collection="code_index_test",
        embed_base_url="http://localhost:1",
        embed_model="test-model",
        embed_dim=8,
        embed_timeout_s=15.0,
        sweep_seconds=45.0,
        debounce_ms=400,
        allowed_exts=registry.extension_allowlist(),
        allowed_filenames=registry.filename_allowlist(),
        ignore_dirs=IGNORE_DIRS,
        vector_store="faiss",
    )


def _seed(settings: Settings, statuses: list[str | None]) -> None:
    with db.connect(settings.index_db_path) as conn, conn:
        db.ensure_schema(conn)
        file_id = db.upsert_file(
            conn,
            FileRecord(
                path="src/foo.py",
                language="python",
                size=10,
                sha256="abc",
                mtime=1.0,
            ),
        )
        db.replace_file_chunks(
            conn,
            file_id,
            [
                Chunk(
                    chunk_index=i,
                    start_line=i + 1,
                    end_line=i + 1,
                    content=f"def f{i}(): pass",
                )
                for i in range(len(statuses))
            ],
        )
        ids = db.chunk_ids_for_path(conn, "src/foo.py")
        db.record_embedding_state(
            conn,
            [
                (chunk_id, f"point-{i}", status)
                for i, ((chunk_id, _), status) in enumerate(zip(ids, statuses))
                if status is not None
            ],
        )


def _stub_empty_search(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        embed, "embed_query", lambda settings, query: [0.0] * settings.embed_dim
    )
    monkeypatch.setattr(vector_store, "search", lambda settings, vector, limit: [])


def test_status_payload_reports_embedding_progress(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _seed(settings, ["ok", None])

    payload = server._status_payload(settings)

    assert payload["vectors_indexed"] == 1
    assert payload["pending_embeddings"] == 1


def test_semantic_search_collapses_overlapping_chunks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    with db.connect(settings.index_db_path) as conn, conn:
        db.ensure_schema(conn)
        for path, spans in (
            ("src/a.py", [(10, 39), (20, 49), (40, 69)]),
            ("src/b.py", [(1, 30)]),
        ):
            file_id = db.upsert_file(
                conn,
                FileRecord(
                    path=path, language="python", size=10, sha256=path, mtime=1.0
                ),
            )
            db.replace_file_chunks(
                conn,
                file_id,
                [
                    Chunk(
                        chunk_index=index,
                        start_line=start,
                        end_line=end,
                        content=f"# {path} {start}-{end}",
                    )
                    for index, (start, end) in enumerate(spans)
                ],
            )
    monkeypatch.setattr(
        embed, "embed_query", lambda settings, query: [0.0] * settings.embed_dim
    )
    monkeypatch.setattr(
        vector_store,
        "search",
        lambda settings, vector, limit: [
            VectorHit("src/a.py", 0, 0.90),  # 10-39
            VectorHit("src/a.py", 1, 0.85),  # 20-49 overlaps the first
            VectorHit("src/a.py", 2, 0.80),  # 40-69 keeps its own span
            VectorHit("src/b.py", 0, 0.75),
        ],
    )

    payload = server._search_code(
        settings, {"query": "anything", "semantic": True, "limit": 3}
    )

    assert [(hit["file"], hit["line"]) for hit in payload["hits"]] == [
        ("src/a.py", 10),
        ("src/a.py", 40),
        ("src/b.py", 1),
    ]


def test_semantic_search_reports_pending_vectors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    _seed(settings, [None])
    _stub_empty_search(monkeypatch)

    payload = server._search_code(settings, {"query": "anything", "semantic": True})

    assert payload["hits"] == []
    assert payload["source"] == "semantic"
    assert payload["ready"] is False
    assert payload["pending_embeddings"] == 1
    assert "still pending embedding" in payload["message"]


def test_semantic_search_reports_ready_without_hits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    _seed(settings, ["ok"])
    _stub_empty_search(monkeypatch)

    payload = server._search_code(settings, {"query": "anything", "semantic": True})

    assert payload["hits"] == []
    assert payload["ready"] is True
    assert payload["pending_embeddings"] == 0
    assert "message" not in payload


def test_semantic_search_reports_unavailable_without_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    _seed(settings, ["ok"])

    def failing_query(settings: Settings, query: str) -> list[float]:
        raise EmbedError("endpoint down")

    monkeypatch.setattr(embed, "embed_query", failing_query)

    payload = server._search_code(settings, {"query": "anything", "semantic": True})

    assert payload["hits"] == []
    assert payload["ready"] is False
    assert payload["pending_embeddings"] == 0
    assert payload["message"].startswith("semantic search unavailable:")
