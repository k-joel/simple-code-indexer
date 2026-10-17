"""Builtin Dart plugin."""

NAME = "dart"
GRAMMAR = "dart"
EXTENSIONS = [".dart"]
FILENAMES: list[str] = []
SYMBOL_NODES = {
    "class_definition": "class",
    "function_signature": "function",
    "method_signature": "method",
}
