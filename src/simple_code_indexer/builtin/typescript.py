"""Builtin TypeScript plugin."""

NAME = "typescript"
GRAMMAR = "typescript"
EXTENSIONS = [".ts", ".tsx"]
FILENAMES: list[str] = []
SYMBOL_NODES = {
    "function_declaration": "function",
    "generator_function_declaration": "function",
    "class_declaration": "class",
    "abstract_class_declaration": "class",
    "interface_declaration": "interface",
    "type_alias_declaration": "type_alias",
    "enum_declaration": "enum",
    "method_definition": "method",
}
