"""
ast_parser.py
=============
Tree-sitter based AST parsing for extracting structural information
from source files: functions, classes, imports, exports, and call sites.

Provides language-agnostic ``parse_file`` that returns an ``ASTResult``
dataclass. Falls back gracefully for unsupported languages.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_PARSERS: Dict[str, Any] = {}
_INIT_DONE = False


def _lazy_init() -> None:
    """Load Tree-sitter languages on first use.

    Populates ``_PARSERS`` with ``(Language, Parser)`` tuples keyed
    by internal language name.  Silently skips unavailable grammars.
    """
    global _INIT_DONE
    if _INIT_DONE:
        return
    _INIT_DONE = True

    try:
        from tree_sitter import Language, Parser
    except ImportError:
        logger.warning("tree-sitter not installed — AST parsing disabled")
        return

    _LANG_MODULES = {
        "python": "tree_sitter_python",
        "javascript": "tree_sitter_javascript",
        "typescript": "tree_sitter_typescript",
        "tsx": "tree_sitter_typescript",
        "java": "tree_sitter_java",
        "go": "tree_sitter_go",
        "rust": "tree_sitter_rust",
    }

    for lang_key, mod_name in _LANG_MODULES.items():
        try:
            mod = __import__(mod_name)
            if lang_key == "tsx":
                lang_obj = Language(mod.language_tsx())
            elif lang_key == "typescript":
                lang_obj = Language(mod.language_typescript())
            else:
                lang_obj = Language(mod.language())
            parser = Parser(lang_obj)
            _PARSERS[lang_key] = (lang_obj, parser)
        except Exception as exc:
            logger.debug("Tree-sitter grammar %s unavailable: %s", lang_key, exc)


EXT_TO_LANG: Dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
}
"""Map file extensions to Tree-sitter language keys."""


@dataclass
class FunctionInfo:
    """Extracted function or method metadata."""
    name: str
    params: str = ""
    start_line: int = 0
    end_line: int = 0
    body_text: str = ""


@dataclass
class ClassInfo:
    """Extracted class metadata."""
    name: str
    methods: List[str] = field(default_factory=list)
    start_line: int = 0
    end_line: int = 0


@dataclass
class ImportInfo:
    """Extracted import statement."""
    module: str
    symbols: List[str] = field(default_factory=list)
    start_line: int = 0


@dataclass
class ExportInfo:
    """Extracted export symbol."""
    name: str
    kind: str = "unknown"
    start_line: int = 0


@dataclass
class CallSite:
    """Extracted function call site."""
    caller: str = ""
    callee: str = ""
    line: int = 0


@dataclass
class ASTResult:
    """Complete AST extraction result for a single file."""
    functions: List[FunctionInfo] = field(default_factory=list)
    classes: List[ClassInfo] = field(default_factory=list)
    imports: List[ImportInfo] = field(default_factory=list)
    exports: List[ExportInfo] = field(default_factory=list)
    call_sites: List[CallSite] = field(default_factory=list)
    language: str = ""
    parsed: bool = False


def _node_text(node: Any, source: bytes) -> str:
    """Extract UTF-8 text for a Tree-sitter node.

    Args:
        node:   Tree-sitter node.
        source: Original source bytes.

    Returns:
        Decoded text of the node.
    """
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _find_enclosing_function(node: Any) -> str:
    """Walk up the tree to find the enclosing function name.

    Args:
        node: Tree-sitter node to start from.

    Returns:
        Function name or empty string.
    """
    parent = node.parent
    func_types = {
        "function_definition", "function_declaration",
        "method_definition", "arrow_function",
        "method_declaration",
    }
    while parent:
        if parent.type in func_types:
            for child in parent.children:
                if child.type in ("identifier", "property_identifier", "name"):
                    return child.text.decode("utf-8", errors="replace") if isinstance(child.text, bytes) else str(child.text)
        parent = parent.parent
    return ""


def _extract_python(root: Any, source: bytes) -> ASTResult:
    """Extract AST data from a Python file.

    Args:
        root:   Tree-sitter root node.
        source: Raw source bytes.

    Returns:
        Populated ``ASTResult``.
    """
    result = ASTResult(language="python", parsed=True)

    def _walk(node: Any) -> None:
        if node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            params_node = node.child_by_field_name("parameters")
            name = _node_text(name_node, source) if name_node else ""
            params = _node_text(params_node, source) if params_node else ""
            body = _node_text(node, source)
            if len(body) > 2000:
                body = body[:2000] + "..."
            result.functions.append(FunctionInfo(
                name=name, params=params,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                body_text=body,
            ))

        elif node.type == "class_definition":
            name_node = node.child_by_field_name("name")
            name = _node_text(name_node, source) if name_node else ""
            methods = []
            for child in node.children:
                if child.type == "block":
                    for stmt in child.children:
                        if stmt.type == "function_definition":
                            mn = stmt.child_by_field_name("name")
                            if mn:
                                methods.append(_node_text(mn, source))
            result.classes.append(ClassInfo(
                name=name, methods=methods,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
            ))

        elif node.type == "import_statement":
            text = _node_text(node, source)
            match = re.match(r"import\s+(\S+)", text)
            module = match.group(1) if match else text
            result.imports.append(ImportInfo(
                module=module, symbols=[],
                start_line=node.start_point[0] + 1,
            ))

        elif node.type == "import_from_statement":
            mod_node = node.child_by_field_name("module_name")
            module = _node_text(mod_node, source) if mod_node else ""
            symbols = []
            found_import_kw = False
            for child in node.children:
                if child.type == "import":
                    found_import_kw = True
                    continue
                if not found_import_kw:
                    continue
                if child.type == "dotted_name" and child != mod_node:
                    symbols.append(_node_text(child, source))
                elif child.type == "identifier":
                    symbols.append(_node_text(child, source))
                elif child.type == "aliased_import":
                    name_child = child.child_by_field_name("name")
                    if name_child:
                        symbols.append(_node_text(name_child, source))
                elif child.type == "wildcard_import":
                    symbols.append("*")
            result.imports.append(ImportInfo(
                module=module, symbols=symbols,
                start_line=node.start_point[0] + 1,
            ))

        elif node.type == "call":
            func_node = node.child_by_field_name("function")
            if func_node:
                callee = _node_text(func_node, source)
                caller = _find_enclosing_function(node)
                result.call_sites.append(CallSite(
                    caller=caller, callee=callee,
                    line=node.start_point[0] + 1,
                ))

        for child in node.children:
            _walk(child)

    _walk(root)
    return result


def _extract_javascript(root: Any, source: bytes, lang: str = "javascript") -> ASTResult:
    """Extract AST data from a JavaScript/TypeScript file.

    Args:
        root:   Tree-sitter root node.
        source: Raw source bytes.
        lang:   Language label for the result.

    Returns:
        Populated ``ASTResult``.
    """
    result = ASTResult(language=lang, parsed=True)

    def _walk(node: Any) -> None:
        if node.type in ("function_declaration", "method_definition", "arrow_function"):
            name_node = node.child_by_field_name("name")
            params_node = node.child_by_field_name("parameters")
            name = _node_text(name_node, source) if name_node else ""
            if not name and node.parent and node.parent.type == "variable_declarator":
                vn = node.parent.child_by_field_name("name")
                if vn:
                    name = _node_text(vn, source)
            params = _node_text(params_node, source) if params_node else ""
            body = _node_text(node, source)
            if len(body) > 2000:
                body = body[:2000] + "..."
            result.functions.append(FunctionInfo(
                name=name, params=params,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                body_text=body,
            ))

        elif node.type == "class_declaration":
            name_node = node.child_by_field_name("name")
            name = _node_text(name_node, source) if name_node else ""
            methods = []
            body_node = node.child_by_field_name("body")
            if body_node:
                for child in body_node.children:
                    if child.type == "method_definition":
                        mn = child.child_by_field_name("name")
                        if mn:
                            methods.append(_node_text(mn, source))
            result.classes.append(ClassInfo(
                name=name, methods=methods,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
            ))

        elif node.type == "import_statement":
            src_node = node.child_by_field_name("source")
            module = _node_text(src_node, source).strip("'\"") if src_node else ""
            symbols = []
            for child in node.children:
                if child.type == "import_clause":
                    for gc in child.children:
                        if gc.type == "identifier":
                            symbols.append(_node_text(gc, source))
                        elif gc.type == "named_imports":
                            for spec in gc.children:
                                if spec.type == "import_specifier":
                                    n = spec.child_by_field_name("name")
                                    if n:
                                        symbols.append(_node_text(n, source))
            result.imports.append(ImportInfo(
                module=module, symbols=symbols,
                start_line=node.start_point[0] + 1,
            ))

        elif node.type in ("export_statement",):
            for child in node.children:
                if child.type in ("function_declaration", "class_declaration"):
                    nn = child.child_by_field_name("name")
                    if nn:
                        result.exports.append(ExportInfo(
                            name=_node_text(nn, source),
                            kind=child.type.replace("_declaration", ""),
                            start_line=node.start_point[0] + 1,
                        ))
                elif child.type == "lexical_declaration":
                    for decl in child.children:
                        if decl.type == "variable_declarator":
                            nn = decl.child_by_field_name("name")
                            if nn:
                                result.exports.append(ExportInfo(
                                    name=_node_text(nn, source),
                                    kind="variable",
                                    start_line=node.start_point[0] + 1,
                                ))

        elif node.type == "call_expression":
            func_node = node.child_by_field_name("function")
            if func_node:
                callee = _node_text(func_node, source)
                caller = _find_enclosing_function(node)
                result.call_sites.append(CallSite(
                    caller=caller, callee=callee,
                    line=node.start_point[0] + 1,
                ))

        for child in node.children:
            _walk(child)

    _walk(root)
    return result


def _extract_generic(root: Any, source: bytes, lang: str) -> ASTResult:
    """Generic extraction for Java, Go, Rust — focuses on functions/methods.

    Args:
        root:   Tree-sitter root node.
        source: Raw source bytes.
        lang:   Language label.

    Returns:
        Populated ``ASTResult``.
    """
    result = ASTResult(language=lang, parsed=True)
    func_types = {
        "function_declaration", "function_definition", "method_declaration",
        "function_item", "impl_item",
    }
    class_types = {
        "class_declaration", "struct_item", "type_declaration",
        "interface_declaration",
    }
    import_types = {
        "import_declaration", "use_declaration",
        "import_spec", "package_clause",
    }

    def _walk(node: Any) -> None:
        if node.type in func_types:
            name_node = node.child_by_field_name("name")
            params_node = node.child_by_field_name("parameters")
            name = _node_text(name_node, source) if name_node else ""
            params = _node_text(params_node, source) if params_node else ""
            body = _node_text(node, source)
            if len(body) > 2000:
                body = body[:2000] + "..."
            result.functions.append(FunctionInfo(
                name=name, params=params,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                body_text=body,
            ))

        elif node.type in class_types:
            name_node = node.child_by_field_name("name")
            name = _node_text(name_node, source) if name_node else ""
            result.classes.append(ClassInfo(
                name=name,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
            ))

        elif node.type in import_types:
            text = _node_text(node, source)
            result.imports.append(ImportInfo(
                module=text.strip(),
                start_line=node.start_point[0] + 1,
            ))

        elif node.type == "call_expression":
            func_node = node.child_by_field_name("function")
            if func_node:
                callee = _node_text(func_node, source)
                caller = _find_enclosing_function(node)
                result.call_sites.append(CallSite(
                    caller=caller, callee=callee,
                    line=node.start_point[0] + 1,
                ))

        for child in node.children:
            _walk(child)

    _walk(root)
    return result


_EXTRACTORS = {
    "python": _extract_python,
    "javascript": _extract_javascript,
    "typescript": lambda r, s: _extract_javascript(r, s, "typescript"),
    "tsx": lambda r, s: _extract_javascript(r, s, "tsx"),
    "java": lambda r, s: _extract_generic(r, s, "java"),
    "go": lambda r, s: _extract_generic(r, s, "go"),
    "rust": lambda r, s: _extract_generic(r, s, "rust"),
}


def parse_file(content: str, file_path: str) -> ASTResult:
    """Parse a source file and extract structural information.

    Uses Tree-sitter for supported languages; returns an empty
    ``ASTResult`` with ``parsed=False`` for unsupported files or
    when Tree-sitter is unavailable.

    Args:
        content:   Full file content as a string.
        file_path: File path (used to determine language by extension).

    Returns:
        ``ASTResult`` with functions, classes, imports, exports, call_sites.
    """
    _lazy_init()

    ext = Path(file_path).suffix.lower()
    lang_key = EXT_TO_LANG.get(ext)
    if not lang_key or lang_key not in _PARSERS:
        return ASTResult(language=lang_key or "", parsed=False)

    _lang_obj, parser = _PARSERS[lang_key]
    source = content.encode("utf-8")

    try:
        tree = parser.parse(source)
    except Exception as exc:
        logger.warning("Tree-sitter parse failed for %s: %s", file_path, exc)
        return ASTResult(language=lang_key, parsed=False)

    extractor = _EXTRACTORS.get(lang_key)
    if not extractor:
        return ASTResult(language=lang_key, parsed=False)

    try:
        return extractor(tree.root_node, source)
    except Exception as exc:
        logger.warning("AST extraction failed for %s: %s", file_path, exc)
        return ASTResult(language=lang_key, parsed=False)


def ast_to_dict(result: ASTResult) -> Dict[str, Any]:
    """Convert an ``ASTResult`` to a JSON-serializable dict for storage.

    Args:
        result: Parsed AST result.

    Returns:
        Dict with lists of functions, classes, imports, exports, call_sites.
    """
    return {
        "functions": [
            {"name": f.name, "params": f.params,
             "start_line": f.start_line, "end_line": f.end_line}
            for f in result.functions
        ],
        "classes": [
            {"name": c.name, "methods": c.methods,
             "start_line": c.start_line, "end_line": c.end_line}
            for c in result.classes
        ],
        "imports": [
            {"module": i.module, "symbols": i.symbols,
             "start_line": i.start_line}
            for i in result.imports
        ],
        "exports": [
            {"name": e.name, "kind": e.kind, "start_line": e.start_line}
            for e in result.exports
        ],
        "call_sites": [
            {"caller": cs.caller, "callee": cs.callee, "line": cs.line}
            for cs in result.call_sites
        ],
        "language": result.language,
        "parsed": result.parsed,
    }
