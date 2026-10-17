"""Builtin C# plugin (pack grammar name is `csharp`)."""

NAME = "c_sharp"
GRAMMAR = "csharp"
EXTENSIONS = [".cs"]
FILENAMES: list[str] = []
SYMBOL_NODES = {
    "class_declaration": "class",
    "interface_declaration": "interface",
    "struct_declaration": "struct",
    "enum_declaration": "enum",
    "method_declaration": "method",
    "constructor_declaration": "constructor",
}
