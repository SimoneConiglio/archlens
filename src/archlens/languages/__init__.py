"""Front-ends for languages other than Python, and helpers they share.

Every front-end fills the same :class:`~archlens.model.Project`: modules (one per source file,
named by their path, with directories as packages), classes with attributes, methods and the
behavioural facts used by the pattern detectors, and resolved references between classes.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Iterable
from pathlib import Path

from ..analyzer import SKIP_DIRS
from ..model import ModuleInfo, Project

EXTENSIONS = {
    "python": (".py",),
    "cpp": (".h", ".hh", ".hpp", ".hxx", ".h++", ".ipp", ".tpp", ".cc", ".cpp", ".cxx", ".c++"),
    "tcl": (".tcl", ".tm", ".itcl"),
}


def source_files(root: Path, language: str, exclude: Iterable[str] = ()) -> list[Path]:
    exts = EXTENSIONS[language]
    if root.is_file():
        return [root] if root.suffix.lower() in exts else []
    patterns = list(exclude)
    found = []
    for f in sorted(root.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in exts:
            continue
        rel = f.relative_to(root)
        if any(p in SKIP_DIRS or p.startswith(".") for p in rel.parts[:-1]):
            continue
        if any(fnmatch.fnmatch(rel.as_posix(), pat) for pat in patterns):
            continue
        found.append(f)
    return found


def detect_languages(root: Path, exclude: Iterable[str] = ()) -> list[str]:
    langs = [lang for lang in EXTENSIONS if source_files(root, lang, exclude)]
    return langs or ["python"]


def add_path_module(project: Project, root: Path, file: Path, language: str) -> ModuleInfo:
    """Register a module named by its relative path (``geo/shape.hpp``); parent directories become packages."""
    base = root if root.is_dir() else root.parent
    rel = file.relative_to(base).as_posix()
    module = ModuleInfo(name=rel, file=rel, language=language)
    project.modules[rel] = module
    parts = rel.split("/")[:-1]
    for i in range(1, len(parts) + 1):
        pkg = "/".join(parts[:i])
        if pkg not in project.modules:
            project.modules[pkg] = ModuleInfo(name=pkg, file=pkg + "/", is_package=True, language=language)
    return module


_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def snake(name: str) -> str:
    """``createButton`` / ``CreateButton`` -> ``create_button`` (used to match naming conventions)."""
    return _CAMEL.sub("_", name).lower()


def visibility_from_name(name: str) -> str:
    if name.startswith("__") and not name.endswith("__"):
        return "private"
    if name.startswith("_"):
        return "protected"
    return "public"
