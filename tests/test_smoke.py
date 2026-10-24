import faiss

from simple_code_indexer import main
from simple_code_indexer.config import load_settings


def test_main_imports() -> None:
    assert callable(main)


def test_faiss_is_importable() -> None:
    assert faiss.__version__


def test_the_default_vector_store_is_faiss(monkeypatch) -> None:
    monkeypatch.delenv("VECTOR_STORE", raising=False)
    monkeypatch.delenv("FAISS_PATH", raising=False)
    assert load_settings().vector_store == "faiss"
