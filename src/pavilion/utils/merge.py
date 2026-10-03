"""Building and extending Python modules from code snippets.

A utility's template is a snippet: import statements plus top-level definitions.
Several utilities share a module (tokens.py holds generate_token, generate_code, ...),
so adding one means merging its imports into the module's import block and appending
its definitions, without touching anything else in the file.
"""

import ast
import sys
from dataclasses import dataclass

# An import as (module, name, alias): `import x` -> ("x", None, None),
# `from x import y as z` -> ("x", "y", "z"). Relative modules keep their dots (".base").
Import = tuple[str, str | None, str | None]


@dataclass(frozen=True)
class Block:
    """A top-level statement (with the comments above it) and the names it defines."""

    names: frozenset[str]
    text: str
    # def/class (isort wants 2 blank lines before those after imports, 1 otherwise).
    definition: bool = False


@dataclass(frozen=True)
class Snippet:
    imports: tuple[Import, ...]
    blocks: tuple[Block, ...]

    @property
    def names(self) -> frozenset[str]:
        return frozenset(name for block in self.blocks for name in block.names)


def _imports_of(node: ast.stmt) -> list[Import]:
    if isinstance(node, ast.Import):
        return [(alias.name, None, alias.asname) for alias in node.names]
    assert isinstance(node, ast.ImportFrom)
    module = "." * node.level + (node.module or "")
    return [(module, alias.name, alias.asname) for alias in node.names]


def _defined_names(node: ast.stmt) -> frozenset[str]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return frozenset({node.name})
    targets = node.targets if isinstance(node, ast.Assign) else [getattr(node, "target", None)]
    return frozenset(t.id for t in targets if isinstance(t, ast.Name))


def _start_line(node: ast.stmt) -> int:
    """1-based first line, including decorators."""
    decorators = getattr(node, "decorator_list", [])
    return min([node.lineno, *(d.lineno for d in decorators)])


def _is_docstring(node: ast.stmt) -> bool:
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(
        node.value.value, str
    )


def split(source: str) -> Snippet:
    """Split a snippet into its imports and its other top-level statements."""
    lines = source.splitlines()
    imports: list[Import] = []
    blocks: list[Block] = []
    previous_end = 0
    for node in ast.parse(source).body:
        assert node.end_lineno is not None
        # Everything since the previous statement, so comments above a def stay with it.
        text = "\n".join(lines[previous_end : node.end_lineno]).strip("\n")
        previous_end = node.end_lineno
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.extend(_imports_of(node))
        elif not _is_docstring(node):
            definition = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            blocks.append(Block(_defined_names(node), text, definition))
    return Snippet(tuple(imports), tuple(blocks))


def _section(module: str) -> int:
    """isort sections: __future__, standard library, third party, local (relative)."""
    if module == "__future__":
        return 0
    if module.startswith("."):
        return 3
    return 1 if module.split(".")[0] in sys.stdlib_module_names else 2


def _name_order(name: str) -> tuple[int, str]:
    # isort's order-by-type: CONSTANTS, then Classes, then functions/variables.
    return (0 if name.isupper() else 1 if name[0].isupper() else 2, name)


def render_imports(imports: list[Import]) -> list[str]:
    """isort-style import lines: sections apart, `import x` before `from x import`."""
    plain = {(m, a) for m, n, a in imports if n is None}
    froms: dict[str, set[tuple[str, str | None]]] = {}
    for module, name, alias in imports:
        if name is not None:
            froms.setdefault(module, set()).add((name, alias))

    sections: dict[int, list[str]] = {}
    for module, alias in sorted(plain):
        line = f"import {module}" + (f" as {alias}" if alias else "")
        sections.setdefault(_section(module), []).append(line)
    for module in sorted(froms):
        names = sorted(froms[module], key=lambda item: _name_order(item[0]))
        parts = ", ".join(n + (f" as {a}" if a else "") for n, a in names)
        sections.setdefault(_section(module), []).append(f"from {module} import {parts}")

    lines: list[str] = []
    for key in sorted(sections):
        if lines:
            lines.append("")
        lines.extend(sections[key])
    return lines


def new_module(docstring: str, snippets: list[Snippet]) -> str:
    """A module made of `snippets`, in order; definitions already present are skipped."""
    imports = [i for snippet in snippets for i in snippet.imports]
    blocks: list[Block] = []
    seen: set[str] = set()
    for snippet in snippets:
        for block in snippet.blocks:
            if block.names and block.names <= seen:
                continue
            seen |= block.names
            blocks.append(block)
    text = f'"""{docstring}"""'
    if imports:
        text += "\n\n" + "\n".join(render_imports(imports))
    for index, block in enumerate(blocks):
        after_imports = index == 0 and imports and not block.definition
        text += ("\n\n" if after_imports else "\n\n\n") + block.text
    return text + "\n"


def defined_names(source: str) -> frozenset[str]:
    return frozenset(
        name for node in ast.parse(source).body for name in _defined_names(node)
    )


def add_to_module(source: str, snippet: Snippet, replace: frozenset[str] = frozenset()) -> str:
    """`source` with the snippet's imports merged in and its definitions appended.

    Definitions whose names already exist are kept as they are, unless they're in
    `replace`, in which case they're swapped for the snippet's version in place.
    """
    tree = ast.parse(source)
    lines = source.splitlines()
    edits: list[tuple[int, int, list[str]]] = []  # 0-based [start, end) -> new lines

    existing: dict[str, ast.stmt] = {}
    for node in tree.body:
        for name in _defined_names(node):
            existing[name] = node
    appended: list[str] = []
    for block in snippet.blocks:
        present = block.names & existing.keys()
        if not present:
            appended.append(block.text)
        elif present & replace:
            node = existing[next(iter(present & replace))]
            assert node.end_lineno is not None
            edits.append((_start_line(node) - 1, node.end_lineno, block.text.splitlines()))
    if appended:
        tail = "\n\n\n".join(appended).splitlines()
        while lines and not lines[-1].strip():
            lines.pop()
        edits.append((len(lines), len(lines), ["", "", *tail] if lines else tail))

    # The leading run of import statements (after an optional docstring).
    body = tree.body[1:] if tree.body and _is_docstring(tree.body[0]) else tree.body
    leading: list[ast.stmt] = []
    for node in body:
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            break
        leading.append(node)
    current = [i for node in leading for i in _imports_of(node)]
    missing = [i for i in snippet.imports if i not in current]
    if missing:
        if leading:
            start, end = _start_line(leading[0]) - 1, leading[-1].end_lineno or 0
            region = lines[start:end]
            if any(line.strip().startswith("#") for line in region):
                # Don't drop comments by rebuilding: add the new imports after the block.
                edits.append((end, end, render_imports(missing)))
            else:
                edits.append((start, end, render_imports(current + missing)))
        else:
            after_docstring = tree.body[0].end_lineno if body is not tree.body else 0
            assert after_docstring is not None
            edits.append((after_docstring, after_docstring, ["", *render_imports(missing)]))

    for start, end, new in sorted(edits, key=lambda edit: edit[0], reverse=True):
        lines[start:end] = new
    return "\n".join(lines) + "\n"
