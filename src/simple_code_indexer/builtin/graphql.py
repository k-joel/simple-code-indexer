"""Builtin GraphQL plugin."""

NAME = "graphql"
GRAMMAR = "graphql"
EXTENSIONS = [".graphql", ".gql"]
FILENAMES: list[str] = []
SYMBOL_NODES = {
    "object_type_definition": "type",
    "interface_type_definition": "interface",
    "enum_type_definition": "enum",
    "input_object_type_definition": "type",
    "union_type_definition": "union",
    "field_definition": "field",
}
