"""Specialized symbol extractors referenced by the catalog.

These beat the generic name-field walker where a grammar has no `name` field on
its declaration nodes (Make rule targets, C/C++ declarator chains) or where the
signature must be trimmed at the body rather than the first `;`.
"""

from __future__ import annotations

import re
from typing import Any

from simple_code_indexer.models import Symbol
from simple_code_indexer.tsutil import signature, text, walk

_PYTHON_SYMBOL_NODES: dict[str, str] = {
    "function_definition": "function",
    "class_definition": "class",
}

_CPP_NAME_NODES: frozenset[str] = frozenset(
    {
        "identifier",
        "field_identifier",
        "qualified_identifier",
        "destructor_name",
        "operator_name",
        "template_function",
        "type_identifier",
    }
)

_CPP_SYMBOL_NODES: dict[str, str] = {
    "function_definition": "function",
    "class_specifier": "class",
    "struct_specifier": "struct",
    # Prototypes / in-class declarations; only kept when they carry a
    # function_declarator (see extract_c_family).
    "declaration": "function",
    "field_declaration": "function",
    "type_definition": "typedef",
    "alias_declaration": "type_alias",
}


def extract_python(root: Any, source: str) -> list[Symbol]:
    """Python functions and classes, signature trimmed at the body colon."""
    symbols: list[Symbol] = []
    for node in walk(root):
        kind = _PYTHON_SYMBOL_NODES.get(node.type)
        if kind is None:
            continue
        name_node = node.child_by_field_name("name")
        if name_node is None:
            continue
        body = node.child_by_field_name("body")
        end = body.start_byte if body is not None else node.end_byte
        raw = source.encode("utf-8")[node.start_byte : end].decode("utf-8").rstrip()
        symbols.append(
            Symbol(
                name=text(name_node, source),
                kind=kind,
                line=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                signature=raw.rstrip(":"),
            )
        )
    return symbols


def extract_make(root: Any, source: str) -> list[Symbol]:
    """Make targets; the generic walker finds nothing (no `name` field).

    `targets` is a named child of `rule`, not a tree-sitter field, so it has to be
    located by node type.
    """
    symbols: list[Symbol] = []
    for node in walk(root):
        if node.type != "rule":
            continue
        targets = next(
            (child for child in node.named_children if child.type == "targets"),
            None,
        )
        if targets is None or targets.named_child_count == 0:
            continue
        name = text(targets.named_children[0], source).strip()
        if not name:
            continue
        symbols.append(
            Symbol(
                name=name,
                kind="rule",
                line=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                signature=text(node, source).splitlines()[0].strip() or None,
            )
        )
    return symbols


def _function_name(node: Any, source: str) -> str | None:
    """Descend the declarator chain until a named identifier node."""
    current = node.child_by_field_name("declarator")
    if current is None:
        current = node.child_by_field_name("name")
    seen = 0
    while current is not None and seen < 10:
        if current.type in _CPP_NAME_NODES:
            return text(current, source)
        nested = current.child_by_field_name("declarator")
        if nested is None:
            nested = current.child_by_field_name("name")
        if nested is None and current.named_child_count > 0:
            nested = current.named_children[0]
        current = nested
        seen += 1
    return None


def _contains_function_declarator(node: Any) -> Any | None:
    for child in node.children:
        if child.type == "function_declarator":
            return child
        found = _contains_function_declarator(child)
        if found is not None:
            return found
    return None


def extract_c_family(root: Any, source: str) -> list[Symbol]:
    """C/C++ declarations resolved through the declarator chain."""
    symbols: list[Symbol] = []
    for node in walk(root):
        kind = _CPP_SYMBOL_NODES.get(node.type)
        if kind is None:
            continue
        if node.type in ("declaration", "field_declaration"):
            # Keep only real function prototypes/members, not `int x;`.
            declarator = _contains_function_declarator(node)
            if declarator is None:
                continue
            name_node = declarator.child_by_field_name("declarator")
            name = None
            if name_node is not None:
                current = name_node
                seen = 0
                while current is not None and seen < 10:
                    if current.type in _CPP_NAME_NODES:
                        name = text(current, source)
                        break
                    current = current.child_by_field_name("declarator") or (
                        current.named_children[0] if current.named_child_count else None
                    )
                    seen += 1
            if name is None:
                continue
            node_signature = text(node, source).rstrip().rstrip(";")
        else:
            name = _function_name(node, source)
            if name is None:
                continue
            node_signature = signature(node, source)
        symbols.append(
            Symbol(
                name=name,
                kind=kind,
                line=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                signature=node_signature or None,
            )
        )
    return symbols


#: HCL/Terraform block labels map to a symbol kind. A block's node type is
#: always `block`; the first `identifier` child is the block type and the
#: `string_lit` labels that follow identify the instance, so neither the generic
#: walker (no `name` field) nor a node-type map can separate them.
_HCL_BLOCK_KINDS: dict[str, str] = {
    "resource": "resource",
    "data": "resource",
    "variable": "variable",
    "module": "module",
    "output": "output",
    "locals": "namespace",
    "provider": "provider",
    "terraform": "namespace",
}


def extract_hcl(root: Any, source: str) -> list[Symbol]:
    """HCL/Terraform blocks as symbols, named by their type and first label.

    `resource "aws_instance" "web" {}` becomes `aws_instance.web`; `variable
    "region" {}` becomes `region`. Blocks whose type is not a known declaration
    (`dynamic`, `lifecycle`, nested `content`) are skipped rather than indexed
    under a meaningless name.
    """
    symbols: list[Symbol] = []
    for node in walk(root):
        if node.type != "block":
            continue
        identifiers = [c for c in node.named_children if c.type == "identifier"]
        if not identifiers:
            continue
        block_type = text(identifiers[0], source).strip()
        kind = _HCL_BLOCK_KINDS.get(block_type)
        if kind is None:
            continue
        labels = [
            text(literal, source).strip().strip('"')
            for child in node.named_children
            if child.type == "string_lit"
            for literal in child.named_children
            if literal.type == "template_literal"
        ]
        name = ".".join([label for label in labels[:2] if label])
        if not name:
            name = block_type
        symbols.append(
            Symbol(
                name=name,
                kind=kind,
                line=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                signature=f"{block_type} {name}".strip(),
            )
        )
    return symbols


#: Lisp-family definition heads and the kind each defines. A `(define …)` form
#: is an ordinary list, so the only thing that marks it as a definition is its
#: first symbol — which no node-type map can express.
_SEXPR_DEFINITIONS: dict[str, str] = {
    "defn": "function",
    "defn-": "function",
    "defmacro": "macro",
    "def": "variable",
    "defonce": "variable",
    "defrecord": "record",
    "defstruct": "struct",
    "defprotocol": "interface",
    "defmulti": "function",
    "defmethod": "method",
    "define": "function",
    "define-syntax": "macro",
    "define-record-type": "record",
    "define-struct": "struct",
    "defun": "function",
    "defvar": "variable",
    "defparameter": "variable",
    "defclass": "class",
    "defpackage": "module",
    "struct": "struct",
}


def extract_sexpr_definitions(root: Any, source: str) -> list[Symbol]:
    """Lisp-family definitions: `(defn name …)`, `(define (name …) …)`.

    The form's first symbol selects the definition kind, and the name is the
    next symbol — except for Scheme's `(define (f a) …)` shape, where the name
    sits inside the parameter list. Non-definition forms (`(println …)`) are
    skipped, which a plain `list` node map cannot do.
    """
    symbols: list[Symbol] = []
    for node in walk(root):
        if node.type not in ("list", "list_lit"):
            continue
        symbols_in_form = [
            c for c in node.named_children if c.type in ("sym_lit", "symbol")
        ]
        if not symbols_in_form:
            continue
        head = text(symbols_in_form[0], source).strip()
        kind = _SEXPR_DEFINITIONS.get(head)
        if kind is None:
            continue
        name = _sexpr_name(node, source)
        if not name:
            continue
        symbols.append(
            Symbol(
                name=name,
                kind=kind,
                line=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                signature=text(node, source).splitlines()[0].strip() or None,
            )
        )
    return symbols


def _sexpr_name(node: Any, source: str) -> str | None:
    """The defined name: the child after the head symbol.

    Two shapes exist. `(defn add-two [a] …)` puts the name in the *next* child;
    `(define (add-two a) …)` puts it as the first symbol of a following list.
    The child order distinguishes them, so counting symbols cannot: Racket's
    `(define (add-two a) a)` has two top-level symbols, and the second (`a`) is
    a body expression, not the name.
    """
    children = node.named_children
    for index, child in enumerate(children):
        if child.type not in ("sym_lit", "symbol"):
            continue
        following = children[index + 1 : index + 2]
        if not following:
            return None
        target = following[0]
        if target.type in ("sym_lit", "symbol"):
            return text(target, source).strip()
        if target.type in ("list_lit", "list"):
            inner = [
                c for c in target.named_children if c.type in ("sym_lit", "symbol")
            ]
            if inner:
                return text(inner[0], source).strip()
        return None
    return None


def extract_cmake(root: Any, source: str) -> list[Symbol]:
    """CMake `function()`/`macro()`: the name is the first command argument.

    `function_def` has no fields; the name lives in
    `function_command -> argument_list -> argument -> unquoted_argument`, so the
    generic walker cannot reach it.
    """
    symbols: list[Symbol] = []
    for node in walk(root):
        if node.type not in ("function_def", "macro_def"):
            continue
        command = next(
            (c for c in node.named_children if c.type != "body"),
            None,
        )
        if command is None:
            continue
        arguments = next(
            (c for c in command.named_children if c.type == "argument_list"),
            None,
        )
        if arguments is None or arguments.named_child_count == 0:
            continue
        first = arguments.named_children[0]
        name = text(first, source).strip()
        if not name:
            continue
        symbols.append(
            Symbol(
                name=name,
                kind="function" if node.type == "function_def" else "macro",
                line=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                signature=text(command, source).strip() or None,
            )
        )
    return symbols


def extract_r_assignment(root: Any, source: str) -> list[Symbol]:
    """R's `name <- function(...)` / `name = function(...)` definitions.

    `function_definition` is an anonymous value in R; the name is the `lhs` of
    the enclosing `binary_operator`. The generic walker would index every
    function under the keyword `function`.
    """
    symbols: list[Symbol] = []
    for node in walk(root):
        if node.type != "binary_operator":
            continue
        rhs = node.child_by_field_name("rhs")
        if rhs is None or rhs.type != "function_definition":
            continue
        name_node = node.child_by_field_name("lhs")
        if name_node is None:
            continue
        name = text(name_node, source).strip()
        if not name:
            continue
        symbols.append(
            Symbol(
                name=name,
                kind="function",
                line=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                signature=source.encode("utf-8")[node.start_byte : rhs.end_byte]
                .decode("utf-8")
                .rstrip()
                .splitlines()[0]
                .strip()
                or None,
            )
        )
    return symbols


#: Elixir declaration keywords and the kind each defines. `defmodule`/`def`/`defp`
#: are all `call` nodes with the keyword as `target`, so the keyword text is the
#: only thing that distinguishes a definition from an ordinary call.
_ELIXIR_DEFINITIONS: dict[str, str] = {
    "defmodule": "module",
    "defprotocol": "interface",
    "defimpl": "impl",
    "defstruct": "struct",
    "defmacro": "macro",
    "defmacrop": "macro",
    "defguard": "macro",
    "defguardp": "macro",
    "defdelegate": "function",
    "defexception": "class",
    "def": "function",
    "defp": "function",
}


def extract_elixir(root: Any, source: str) -> list[Symbol]:
    """Elixir definitions: a `call` whose `target` is a `def*` keyword.

    The defined name is the first identifier inside the call's `arguments`
    (`def add_two(a) do` -> `add_two`). `defmodule Demo do` names an alias, so
    that shape resolves to the module name.
    """
    symbols: list[Symbol] = []
    for node in walk(root):
        if node.type != "call":
            continue
        target = node.child_by_field_name("target")
        if target is None or target.type != "identifier":
            continue
        keyword = text(target, source).strip()
        kind = _ELIXIR_DEFINITIONS.get(keyword)
        if kind is None:
            continue
        name = _elixir_name(node, source)
        if not name:
            continue
        symbols.append(
            Symbol(
                name=name,
                kind=kind,
                line=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                signature=(keyword + " " + name),
            )
        )
    return symbols


def _elixir_name(node: Any, source: str) -> str | None:
    """The defined name from the call's `arguments` node.

    `arguments` is a child *node*, not a tree-sitter field, so it is located by
    type. `def add_two(a) do` wraps the name in a nested `call` whose target is
    the name; `defmodule Demo do` puts an `alias` there directly.
    """
    arguments = next((c for c in node.named_children if c.type == "arguments"), None)
    if arguments is None:
        return None
    stack = list(arguments.named_children)
    while stack:
        current = stack.pop(0)
        if current.type in ("alias", "identifier"):
            value = text(current, source).strip()
            if value:
                return value
        if current.type == "call":
            target = current.child_by_field_name("target")
            if target is not None and target.type == "identifier":
                value = text(target, source).strip()
                if value:
                    return value
        stack.extend(current.named_children)
    return None


#: Twig `{% … %}` tags that define a reusable name. The tag word is the first
#: `tag` child of the enclosing `statement_directive`, and the defined name is the
#: node after it — a `method` for `macro` (parsed as a call) and a `variable` for
#: `block`.
_TWIG_DEFINITIONS: dict[str, str] = {
    "macro": "macro",
    "block": "block",
}

#: Jinja's grammar has no declaration nodes: every `{% … %}` becomes an opaque
#: `jinja_expression`, so the tag has to be read from the directive's text. Like
#: Twig's, these are the tags that bind a name its templates can call or extend.
_JINJA_DEFINITIONS: dict[str, str] = {
    "macro": "macro",
    "block": "block",
    "call": "macro",
}

_TEMPLATE_TAG = re.compile(r"\{%[-+]?\s*([A-Za-z_]\w*)\s+(?:\s*[A-Za-z_][\w.]*\s+)?")
_TEMPLATE_NAME = re.compile(r"[A-Za-z_][\w.]*")


def extract_twig(root: Any, source: str) -> list[Symbol]:
    """Twig `{% macro name(…) %}` and `{% block name %}` declarations.

    `macro_statement` and `tag_statement` carry no fields, and both include their
    closing tag when the block is unclosed, so the name is taken from the child
    node that follows the tag word and the span stops at the declaration's own
    end rather than at the body.
    """
    symbols: list[Symbol] = []
    for node in walk(root):
        name = None
        kind = None
        if node.type == "macro_statement":
            kind = "macro"
            # A nested macro is `{% macro forms.input(…) %}` and its `method`
            # child only holds the last segment, so the dotted name comes from
            # the statement text up to the parameter list.
            parameters = next(
                (c for c in node.named_children if c.type == "parameters"), None
            )
            end = parameters.start_byte if parameters is not None else node.end_byte
            name = text(node, source)[: end - node.start_byte].split(maxsplit=1)[-1]
            name = name.split("(", 1)[0].strip() or None
        elif node.type == "tag_statement":
            tag = next(
                (
                    text(c, source).strip()
                    for c in node.named_children
                    if c.type == "tag"
                ),
                "",
            )
            kind = _TWIG_DEFINITIONS.get(tag)
            if kind is not None:
                name = next(
                    (
                        text(c, source).strip()
                        for c in node.named_children
                        if c.type == "variable"
                    ),
                    None,
                )
        if not kind or not name:
            continue
        symbols.append(
            Symbol(
                name=name,
                kind=kind,
                line=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                signature=text(node, source).strip() or None,
            )
        )
    return symbols


def extract_jinja(root: Any, source: str) -> list[Symbol]:
    """Jinja `{% macro name(…) %}`, `{% call name(…) %}` and `{% block name %}`.

    The grammar collapses every statement tag into `jinja_expression` (statement
    tags parse to an error inside Jinja's own grammar), so the declaration is read
    from the tag text. Only the opening line is considered: a directive node that
    spans a whole block would otherwise name the tag that closes it.
    """
    symbols: list[Symbol] = []
    for node in walk(root):
        if node.type != "jinja_expression":
            continue
        header = text(node, source).strip()
        if not header:
            continue
        header = header.splitlines()[0]
        match = _TEMPLATE_TAG.search(header)
        if match is None:
            continue
        kind = _JINJA_DEFINITIONS.get(match.group(1))
        if kind is None:
            continue
        remainder = header[match.end() :]
        name_match = _TEMPLATE_NAME.search(remainder)
        if name_match is None:
            continue
        symbols.append(
            Symbol(
                name=name_match.group(0),
                kind=kind,
                line=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                signature=header.strip(),
            )
        )
    return symbols
