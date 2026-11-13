"""Per-workspace sidecar writer: discovery, control protocol, leases, client."""

from simple_code_indexer.sidecar.client import ReaderSession
from simple_code_indexer.sidecar.paths import PROTOCOL_VERSION, state_paths

__all__ = ["PROTOCOL_VERSION", "ReaderSession", "state_paths"]
