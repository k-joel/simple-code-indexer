"""Small exception hierarchy (TDD §10) — catch at process boundaries only."""


class IndexerError(Exception):
    """Base error for the code index."""


class EmbedError(IndexerError):
    """Embedding endpoint failure or dimension mismatch."""


class ParseError(IndexerError):
    """Source could not be decoded or parsed."""


class VectorStoreUnavailable(IndexerError):
    """The configured vector store is unreachable, broken or misconfigured."""


class QdrantUnavailable(VectorStoreUnavailable):
    """Qdrant is unreachable or rejected a request."""


class ConfigError(IndexerError):
    """A config file or config-derived value is invalid."""
