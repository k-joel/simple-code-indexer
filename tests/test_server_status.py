"""get_status embedding progress and semantic-search readiness."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from simple_code_indexer import db, embed, server, vector_store
from simple_code_indexer.config import IGNORE_DIRS, Settings
from simple_code_indexer.errors import EmbedError
from simple_code_indexer.models import Chunk, FileRecord, VectorHit
from simple_code_indexer.registry import get_registry
from simple_code_indexer.sidecar import ReaderSession


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
    assert payload["sweep_seconds"] == 45.0
    assert payload["workspace"] == str(tmp_path)
    assert payload["workspace_source"] == "cwd"


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


class _FakeSession:
    def __init__(self, status: dict[str, Any] | None) -> None:
        self._status = status

    def status(self, timeout: float = 3.0) -> dict[str, Any] | None:
        return self._status


def test_status_payload_merges_the_daemon_status_in_reader_mode(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    _seed(settings, ["ok"])
    status = {
        "type": "status",
        "writer_pid": 999,
        "writer_ok": True,
        "writer_heartbeat_age_s": 0.5,
        "writer_log_file": "writer.log",
        "endpoint": "pipe",
        "sessions": 2,
        "harnesses": [{"pid": 1, "name": "opencode-cli.exe"}],
        "watcher_alive": True,
        "last_sweep": "2026-01-01T00:00:00+00:00",
        "ignored_dirs": 3,
        "ignored_files": 4,
        "vector_store_ok": True,
        "services": {"embedding": "running"},
        "vector_index_age_s": 5.0,
    }
    session = cast(ReaderSession, _FakeSession(status))

    payload = server._status_payload(settings, role="reader", session=session)

    assert payload["role"] == "reader"
    assert payload["index_ready"] is True
    assert payload["writer_pid"] == 999
    assert payload["writer_ok"] is True
    assert payload["writer_heartbeat_age_s"] == 0.5
    assert payload["writer_log_file"] == "writer.log"
    assert payload["daemon_endpoint"] == "pipe"
    assert payload["sessions"] == 2
    assert payload["harnesses"] == [{"pid": 1, "name": "opencode-cli.exe"}]
    assert payload["watcher_alive"] is True
    assert payload["last_sweep"] == "2026-01-01T00:00:00+00:00"
    assert payload["ignored_dirs"] == 3
    assert payload["ignored_files"] == 4
    assert payload["vector_index_age_s"] == 5.0
    assert payload["vectors_indexed"] == 1


def test_status_payload_reports_a_missing_index(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    payload = server._status_payload(settings)

    assert payload["role"] == "writer"
    assert payload["index_ready"] is False
    assert payload["files_indexed"] == 0
    assert payload["symbols_indexed"] == 0
    assert payload["chunks_indexed"] == 0
    assert payload["writer_ok"] is True


def test_status_payload_reader_without_a_daemon_falls_back_to_meta(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    session = cast(ReaderSession, _FakeSession(None))

    payload = server._status_payload(settings, role="reader", session=session)

    assert payload["role"] == "reader"
    assert payload["index_ready"] is False
    assert payload["writer_pid"] is None
    assert payload["writer_ok"] is False
    assert payload["sessions"] == 0
    assert payload["watcher_alive"] is False
    assert payload["writer_log_file"].endswith("writer.log")


def test_search_and_symbol_lookup_are_soft_when_the_index_is_missing(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)

    lexical = server._search_code(settings, {"query": "anything"})
    symbols = server._symbol_lookup(settings, {"symbol": "anything"})

    assert lexical["hits"] == []
    assert lexical["ready"] is False
    assert symbols["found"] is False
    assert symbols["ready"] is False
    assert not settings.index_db_path.exists()
