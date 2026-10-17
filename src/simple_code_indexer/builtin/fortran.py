"""Builtin Fortran plugin."""

NAME = "fortran"
GRAMMAR = "fortran"
EXTENSIONS = [".f", ".f90", ".f95", ".f03", ".f08"]
FILENAMES: list[str] = []
SYMBOL_NODES = {
    "function": "function",
    "subroutine": "function",
    "type": "type",
}
