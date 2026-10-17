"""Small exception hierarchy (TDD §10) — catch at process boundaries only."""


class IndexerError(Exception):
    """Base error for the code index."""


class EmbedError(IndexerError):
    """Embedding endpoint failure or dimension mismatch."""


class ParseError(IndexerError):
    """Source could not be decoded or parsed."""


class QdrantUnavailable(IndexerError):
    """Qdrant is unreachable or rejected a request."""
