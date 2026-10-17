"""Builtin Haskell plugin."""

NAME = "haskell"
GRAMMAR = "haskell"
EXTENSIONS = [".hs", ".lhs"]
FILENAMES: list[str] = []
SYMBOL_NODES = {
    "function": "function",
    "signature": "signature",
    "data_type": "type",
    "newtype": "type",
    "class": "class",
    "instance": "instance",
}
