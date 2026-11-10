from pathlib import Path

import faiss
import pytest

from simple_code_indexer import main, server
from simple_code_indexer.config import load_settings


def test_main_imports() -> None:
    assert callable(main)


def test_main_refuses_the_inferred_home_workspace(
    tmp_path: Path, monkeypatch, caplog
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.delenv("WORKSPACE_ROOT", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.chdir(home)
    with pytest.raises(SystemExit) as excinfo:
        server.main()
    assert excinfo.value.code == 1
    assert "refusing to index it" in caplog.text


def test_faiss_is_importable() -> None:
    assert faiss.__version__


def test_the_default_vector_store_is_faiss(monkeypatch) -> None:
    monkeypatch.delenv("VECTOR_STORE", raising=False)
    monkeypatch.delenv("FAISS_PATH", raising=False)
    assert load_settings().vector_store == "faiss"
