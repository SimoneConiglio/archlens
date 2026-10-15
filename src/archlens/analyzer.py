"""Static analysis of a Python package using the standard library ``ast`` module.

Nothing is imported or executed: the source is parsed, and classes, attributes,
methods and the relations between classes are reconstructed from the syntax tree.
"""

from __future__ import annotations

import ast
import fnmatch
from collections.abc import Iterable, Iterator
from pathlib import Path

from .model import Attribute, ClassInfo, Method, ModuleInfo, Param, Project, Relation, TypeRef

SKIP_DIRS = {
    "__pycache__", ".git", ".hg", ".svn", ".tox", ".nox", ".venv", "venv", "env",
    "build", "dist", "node_modules", "site-packages", ".mypy_cache", ".pytest_cache",
    ".eggs",
}

COLLECTIONS = {
    "list", "List", "set", "Set", "frozenset", "FrozenSet", "tuple", "Tuple", "dict", "Dict",
    "Sequence", "MutableSequence", "Iterable", "Iterator", "Collection", "Mapping",
    "MutableMapping", "deque", "Deque", "defaultdict", "DefaultDict", "OrderedDict",
    "AbstractSet", "MutableSet", "Generator", "AsyncIterator", "AsyncIterable", "WeakSet",
    "WeakValueDictionary", "WeakKeyDictionary",
}
WRAPPERS = {"ClassVar", "Final", "Annotated", "Required", "NotRequired", "ReadOnly", "InitVar"}
LITERAL_FACTORIES = {"list", "dict", "set", "tuple", "frozenset", "defaultdict", "deque", "OrderedDict", "Counter"}
DATA_DECORATORS = {"dataclass", "dataclasses.dataclass", "attr.s", "attrs.define", "attr.define",
                   "define", "frozen", "attrs.frozen", "attr.attrs", "pydantic.dataclasses.dataclass"}
ENUM_BASES = {"Enum", "IntEnum", "StrEnum", "Flag", "IntFlag", "ReprEnum"}


# --------------------------------------------------------------------------- helpers

def dotted(node: ast.AST | None) -> str | None:
    """Return ``a.b.c`` for Name/Attribute chains, ``None`` otherwise."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def unparse(node: ast.AST | None, limit: int = 120) -> str | None:
    if node is None:
        return None
    try:
        text = ast.unparse(node)
    except Exception:  # pragma: no cover - defensive
        return None
    return text if len(text) <= limit else text[: limit - 1] + "…"


def visibility(name: str) -> str:
    if name.startswith("__") and not name.endswith("__"):
        return "private"
    if name.startswith("_") and not (name.startswith("__") and name.endswith("__")):
        return "protected"
    return "public"


def type_refs(node: ast.AST | None, mult: str = "1") -> list[TypeRef]:
    """Extract class names referenced by a type annotation, with multiplicity."""
    if node is None:
        return []
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            try:
                return type_refs(ast.parse(node.value, mode="eval").body, mult)
            except SyntaxError:
                return []
        return []
    if isinstance(node, (ast.Name, ast.Attribute)):
        name = dotted(node)
        return [TypeRef(name, mult)] if name and name != "None" else []
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        has_none = any(isinstance(side, ast.Constant) and side.value is None for side in (node.left, node.right))
        inner = "0..1" if has_none and mult == "1" else mult
        return type_refs(node.left, inner) + type_refs(node.right, inner)
    if isinstance(node, ast.Subscript):
        base = dotted(node.value) or ""
        short = base.rsplit(".", 1)[-1]
        args = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
        if short in COLLECTIONS:
            refs: list[TypeRef] = []
            if short in {"dict", "Dict", "Mapping", "MutableMapping", "defaultdict", "DefaultDict", "OrderedDict"}:
                args = args[1:] if len(args) > 1 else args
            for a in args:
                refs += type_refs(a, "*")
            return refs
        if short == "Optional":
            return [r for a in args for r in type_refs(a, "0..1" if mult == "1" else mult)]
        if short == "Union":
            has_none = any(isinstance(a, ast.Constant) and a.value is None for a in args)
            inner = "0..1" if has_none and mult == "1" else mult
            return [r for a in args for r in type_refs(a, inner)]
        if short in WRAPPERS:
            return type_refs(args[0], mult) if args else []
        if short in {"Literal", "Callable", "Awaitable", "Coroutine"}:
            return []
        if short in {"type", "Type"}:
            return [r for a in args for r in type_refs(a, mult)]
        refs = [TypeRef(base, mult)] if base else []
        for a in args:
            refs += type_refs(a, mult)
        return refs
    if isinstance(node, (ast.Tuple, ast.List)):
        return [r for e in node.elts for r in type_refs(e, mult)]
    return []


def is_stub_body(body: list[ast.stmt]) -> bool:
    stmts = list(body)
    if stmts and isinstance(stmts[0], ast.Expr) and isinstance(stmts[0].value, ast.Constant) \
            and isinstance(stmts[0].value.value, str):
        stmts = stmts[1:]
    if not stmts:
        return True
    for s in stmts:
        if isinstance(s, ast.Pass):
            continue
        if isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and s.value.value is Ellipsis:
            continue
        if isinstance(s, ast.Raise) and s.exc is not None and \
                (dotted(s.exc) or dotted(getattr(s.exc, "func", None)) or "").endswith("NotImplementedError"):
            continue
        if isinstance(s, ast.Return) and (s.value is None or (isinstance(s.value, ast.Constant) and s.value.value is None)):
            continue
        return False
    return True


def _decorator_name(node: ast.expr) -> str:
    target = node.func if isinstance(node, ast.Call) else node
    return dotted(target) or unparse(node) or "?"


def _walk_no_nested(node: ast.AST) -> Iterator[ast.AST]:
    """Walk a function body (including nested closures) without descending into nested classes."""
    stack = list(ast.iter_child_nodes(node))
    while stack:
        cur = stack.pop()
        yield cur
        if isinstance(cur, ast.ClassDef):
            continue
        stack.extend(ast.iter_child_nodes(cur))


def _add(lst: list[str], value: str) -> None:
    if value not in lst:
        lst.append(value)


# --------------------------------------------------------------------------- module discovery

def discover(path: Path, exclude: Iterable[str] = ()) -> list[tuple[Path, str, bool]]:
    """Return ``(file, module_name, is_package)`` triples for every Python file under ``path``."""
    path = path.resolve()
    if path.is_file():
        return [(path, path.stem, False)]
    base = path.parent if (path / "__init__.py").exists() else path
    patterns = list(exclude)
    found = []
    for f in sorted(path.rglob("*.py")):
        rel = f.relative_to(base)
        if any(p in SKIP_DIRS or (p.startswith(".") and p not in (".", "..")) for p in rel.parts[:-1]):
            continue
        rel_posix = rel.as_posix()
        rel_to_path = f.relative_to(path).as_posix()
        if any(fnmatch.fnmatch(rel_posix, pat) or fnmatch.fnmatch(rel_to_path, pat) for pat in patterns):
            continue
        parts = list(rel.with_suffix("").parts)
        is_pkg = parts[-1] == "__init__"
        if is_pkg:
            parts = parts[:-1]
        if not parts or not all(p.isidentifier() for p in parts):
            continue
        found.append((f, ".".join(parts), is_pkg))
    return found


# --------------------------------------------------------------------------- per-module analysis

class ModuleAnalyzer:
    def __init__(self, tree: ast.Module, module: ModuleInfo, rel_file: str):
        self.tree = tree
        self.module = module
        self.rel_file = rel_file
        self.classes: list[ClassInfo] = []

    # imports ---------------------------------------------------------------
    def collect_imports(self) -> None:
        mod = self.module
        package = mod.name if mod.is_package else mod.name.rpartition(".")[0]
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.asname:
                        mod.imports[alias.asname] = alias.name
                    else:
                        first = alias.name.split(".")[0]
                        mod.imports[first] = first
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    parts = package.split(".") if package else []
                    if node.level > 1:
                        parts = parts[: len(parts) - (node.level - 1)]
                    base = ".".join(parts)
                    source = f"{base}.{node.module}" if node.module and base else (node.module or base)
                else:
                    source = node.module or ""
                for alias in node.names:
                    if alias.name == "*":
                        mod.imports.setdefault("*", "")
                        mod.imports["*"] = ",".join(filter(None, [mod.imports["*"], source]))
                        continue
                    mod.imports[alias.asname or alias.name] = f"{source}.{alias.name}" if source else alias.name

    # classes ---------------------------------------------------------------
    def run(self) -> list[ClassInfo]:
        self.collect_imports()
        doc = ast.get_docstring(self.tree)
        self.module.docstring = doc.strip() if doc else None
        self._visit_body(self.tree.body, prefix="")
        return self.classes

    def _visit_body(self, body: list[ast.stmt], prefix: str) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                self._visit_class(node, prefix)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not prefix:
                self.module.functions.append(node.name)
            elif isinstance(node, ast.If):
                self._visit_body(node.body, prefix)
                self._visit_body(node.orelse, prefix)
            elif isinstance(node, ast.Try) or (hasattr(ast, "TryStar") and isinstance(node, ast.TryStar)):
                self._visit_body(node.body, prefix)
                for h in node.handlers:
                    self._visit_body(h.body, prefix)
                self._visit_body(node.orelse, prefix)

    def _visit_class(self, node: ast.ClassDef, prefix: str) -> None:
        qual = f"{prefix}{node.name}"
        doc = ast.get_docstring(node)
        cls = ClassInfo(
            id=f"{self.module.name}.{qual}",
            name=node.name,
            qualname=qual,
            module=self.module.name,
            file=self.rel_file,
            lineno=node.lineno,
            end_lineno=getattr(node, "end_lineno", None),
            docstring=doc.strip() if doc else None,
            bases=[unparse(b) or "?" for b in node.bases],
            decorators=[_decorator_name(d) for d in node.decorator_list],
        )
        for kw in node.keywords:
            if kw.arg == "metaclass":
                cls.metaclass = unparse(kw.value)
        self._classify(cls, node)
        self._collect_members(cls, node)
        self.classes.append(cls)
        self.module.classes.append(cls.id)
        self._visit_body(node.body, prefix=f"{qual}.")

    def _classify(self, cls: ClassInfo, node: ast.ClassDef) -> None:
        short_bases = [(dotted(b.value if isinstance(b, ast.Subscript) else b) or "").rsplit(".", 1)[-1]
                       for b in node.bases]
        st = cls.stereotypes
        for d in node.decorator_list:
            name = _decorator_name(d)
            if name in DATA_DECORATORS or name.endswith(".dataclass"):
                _add(st, "dataclass" if "dataclass" in name else "attrs")
                if isinstance(d, ast.Call) and any(
                        k.arg == "frozen" and isinstance(k.value, ast.Constant) and k.value.value for k in d.keywords):
                    _add(st, "frozen")
            if name in {"frozen", "attrs.frozen"}:
                _add(st, "frozen")
        if any(b in ENUM_BASES for b in short_bases):
            _add(st, "enum")
        if "Protocol" in short_bases:
            _add(st, "protocol")
        if "NamedTuple" in short_bases:
            _add(st, "namedtuple")
        if "TypedDict" in short_bases:
            _add(st, "typeddict")
        if "BaseModel" in short_bases:
            _add(st, "model")
        if any(b.endswith(("Exception", "Error", "Warning")) for b in short_bases):
            _add(st, "exception")
        meta = (cls.metaclass or "").rsplit(".", 1)[-1]
        if "ABC" in short_bases or meta == "ABCMeta":
            _add(st, "abstract")
        if "type" in short_bases or any(b.endswith("Meta") for b in short_bases if b != "ABCMeta"):
            _add(st, "metaclass")
        if "Generic" in short_bases or any(isinstance(b, ast.Subscript) for b in node.bases):
            _add(st, "generic")

    # members ---------------------------------------------------------------
    def _collect_members(self, cls: ClassInfo, node: ast.ClassDef) -> None:
        is_data = any(s in cls.stereotypes for s in ("dataclass", "attrs", "namedtuple", "typeddict", "model"))
        is_enum = "enum" in cls.stereotypes
        attrs: dict[str, Attribute] = {}
        setters: set[str] = set()

        def put(attr: Attribute) -> None:
            existing = attrs.get(attr.name)
            if existing is None:
                attrs[attr.name] = attr
                return
            # Merge: keep the most informative description.
            if not existing.type and attr.type:
                existing.type = attr.type
            if not existing.refs and attr.refs:
                existing.refs = attr.refs
            if existing.origin in ("unknown", "literal", "annotated") and attr.origin in ("created", "injected"):
                existing.origin = attr.origin
            if existing.default is None and attr.default is not None:
                existing.default = attr.default

        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                name = stmt.target.id
                ann = stmt.annotation
                ann_name = (dotted(ann.value if isinstance(ann, ast.Subscript) else ann) or "").rsplit(".", 1)[-1]
                is_classvar = ann_name == "ClassVar"
                origin = "annotated"
                default = unparse(stmt.value, 60)
                refs = type_refs(ann)
                if isinstance(stmt.value, ast.Call) and (dotted(stmt.value.func) or "").endswith("field"):
                    for kw in stmt.value.keywords:
                        if kw.arg in ("default_factory", "factory"):
                            origin = "created"
                            default = f"{unparse(kw.value, 40)}()"
                        elif kw.arg == "default":
                            default = unparse(kw.value, 60)
                    if not any(kw.arg in ("default_factory", "factory", "default") for kw in stmt.value.keywords):
                        default = None
                elif stmt.value is not None:
                    _, vrefs, vorigin = self._infer_value(stmt.value, {})
                    if vorigin == "created":
                        origin = "created"
                scope = "class" if is_classvar or not (is_data or stmt.value is None) else "instance"
                put(Attribute(name=name, type=unparse(ann, 80), default=default, scope=scope,
                              visibility=visibility(name), origin=origin, lineno=stmt.lineno, refs=refs))
            elif isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    for t in (target.elts if isinstance(target, ast.Tuple) else [target]):
                        if not isinstance(t, ast.Name):
                            continue
                        if t.id in ("__slots__", "__match_args__", "__all__"):
                            continue
                        type_str, refs, origin = self._infer_value(stmt.value, {})
                        put(Attribute(name=t.id, type=type_str, default=unparse(stmt.value, 60),
                                      scope="class", kind="enum_member" if is_enum else "field",
                                      visibility=visibility(t.id), origin=origin, lineno=stmt.lineno, refs=refs))
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                decos = [_decorator_name(d) for d in stmt.decorator_list]
                short = [d.rsplit(".", 1)[-1] for d in decos]
                if "property" in short or "cached_property" in short:
                    ret = unparse(stmt.returns, 80)
                    put(Attribute(name=stmt.name, type=ret, scope="instance", kind="property",
                                  visibility=visibility(stmt.name), origin="unknown", readonly=True,
                                  lineno=stmt.lineno, refs=type_refs(stmt.returns)))
                    # still record facts of the getter (useful for proxies) as a hidden method
                    continue
                if any(d.endswith((".setter", ".deleter")) for d in decos):
                    setters.add(stmt.name)
                    continue
                method = self._method(cls, stmt, decos)
                cls.methods.append(method)
                for name, attr in self._self_assignments(stmt, method).items():
                    put(attr)

        for name in setters:
            if name in attrs:
                attrs[name].readonly = False
        cls.attributes = list(attrs.values())
        if any(m.is_abstract for m in cls.methods):
            _add(cls.stereotypes, "abstract")
        cls.is_abstract = "abstract" in cls.stereotypes or "protocol" in cls.stereotypes

    def _method(self, cls: ClassInfo, fn: ast.FunctionDef | ast.AsyncFunctionDef, decos: list[str]) -> Method:
        short = [d.rsplit(".", 1)[-1] for d in decos]
        doc = ast.get_docstring(fn)
        m = Method(
            name=fn.name,
            returns=unparse(fn.returns, 80),
            decorators=decos,
            visibility=visibility(fn.name),
            is_abstract="abstractmethod" in short or "abstractproperty" in short,
            is_static="staticmethod" in short,
            is_classmethod="classmethod" in short,
            is_async=isinstance(fn, ast.AsyncFunctionDef),
            is_stub=is_stub_body(fn.body),
            lineno=fn.lineno,
            docstring=doc.strip().splitlines()[0] if doc else None,
        )
        args = fn.args
        positional = list(args.posonlyargs) + list(args.args)
        defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
        for i, (a, d) in enumerate(zip(positional, defaults)):
            if i == 0 and not m.is_static and a.arg in ("self", "cls", "mcs", "metacls"):
                continue
            m.params.append(Param(a.arg, unparse(a.annotation, 60), unparse(d, 40)))
        if args.vararg:
            m.params.append(Param(args.vararg.arg, unparse(args.vararg.annotation, 60), kind="vararg"))
        for a, d in zip(args.kwonlyargs, args.kw_defaults):
            m.params.append(Param(a.arg, unparse(a.annotation, 60), unparse(d, 40), kind="kwonly"))
        if args.kwarg:
            m.params.append(Param(args.kwarg.arg, unparse(args.kwarg.annotation, 60), kind="kwarg"))
        for a in positional + list(args.kwonlyargs) + [x for x in (args.vararg, args.kwarg) if x]:
            m.ref_names += type_refs(a.annotation)
        m.ref_names += type_refs(fn.returns)
        self._method_facts(cls, fn, m)
        return m

    def _method_facts(self, cls: ClassInfo, fn: ast.FunctionDef | ast.AsyncFunctionDef, m: Method) -> None:
        first = fn.args.posonlyargs[0].arg if fn.args.posonlyargs else (fn.args.args[0].arg if fn.args.args else None)
        self_name = None if m.is_static else first
        cls_names = {cls.name, "cls"} | ({self_name} if m.is_classmethod and self_name else set())
        loop_vars: dict[str, str] = {}

        def self_attr(node: ast.AST) -> str | None:
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == self_name:
                return node.attr
            return None

        def iter_source(node: ast.AST) -> str | None:
            # self.x, self.x.values(), list(self.x), self.x.copy(), sorted(self.x)
            if (a := self_attr(node)) is not None:
                return a
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    return iter_source(node.func.value)
                if node.args:
                    return iter_source(node.args[0])
            return None

        for node in _walk_no_nested(fn):
            if isinstance(node, (ast.Yield, ast.YieldFrom)):
                m.is_generator = True
            elif isinstance(node, ast.Return) and isinstance(node.value, ast.Name) and node.value.id == self_name \
                    and not m.is_classmethod:
                m.returns_self = True
            elif isinstance(node, ast.Raise) and node.exc is not None:
                if (dotted(node.exc) or dotted(getattr(node.exc, "func", None)) or "").endswith("NotImplementedError"):
                    m.raises_not_implemented = True
            elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
                src = iter_source(node.iter)
                if src is not None:
                    _add(m.iterated_attrs, src)
                    if isinstance(node.target, ast.Name):
                        loop_vars[node.target.id] = src
            elif isinstance(node, ast.Call):
                func = node.func
                name = dotted(func)
                if name:
                    _add(m.calls, name)
                if isinstance(func, ast.Attribute):
                    if isinstance(func.value, ast.Name) and func.value.id == self_name:
                        _add(m.self_calls, func.attr)
                    elif (a := self_attr(func.value)) is not None:
                        m.attr_calls.setdefault(a, [])
                        _add(m.attr_calls[a], func.attr)
                    elif isinstance(func.value, ast.Name):
                        m.name_calls.setdefault(func.value.id, [])
                        _add(m.name_calls[func.value.id], func.attr)
                elif isinstance(func, ast.Name) and func.id in loop_vars:
                    m.name_calls.setdefault(func.id, [])
                    _add(m.name_calls[func.id], "__call__")
                # getattr(self._x, name) is typical for dynamic delegation
                if isinstance(func, ast.Name) and func.id == "getattr" and node.args:
                    if (a := self_attr(node.args[0])) is not None:
                        m.attr_calls.setdefault(a, [])
                        _add(m.attr_calls[a], "__getattr__")
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in cls_names:
                _add(m.class_attr_refs, node.attr)
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Call) \
                    and dotted(node.value.func) == "type" and node.value.args:
                _add(m.class_attr_refs, node.attr)
            if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in targets:
                    base = t.value if isinstance(t, ast.Subscript) else t
                    if (a := self_attr(base)) is not None:
                        _add(m.attr_writes, a)
                    elif isinstance(base, ast.Attribute) and isinstance(base.value, ast.Name) \
                            and base.value.id in cls_names:
                        _add(m.attr_writes, base.attr)
        # loop variables calling methods: `for o in self._observers: o.update()`
        for var, src in loop_vars.items():
            if var in m.name_calls:
                m.attr_calls.setdefault(src, [])
                for call in m.name_calls[var]:
                    _add(m.attr_calls[src], call)

    def _self_assignments(self, fn: ast.FunctionDef | ast.AsyncFunctionDef, method: Method) -> dict[str, Attribute]:
        if method.is_static or method.is_classmethod or not (fn.args.args or fn.args.posonlyargs):
            return {}
        self_name = (fn.args.posonlyargs or fn.args.args)[0].arg
        params: dict[str, ast.expr | None] = {}
        for a in list(fn.args.posonlyargs) + list(fn.args.args)[1:] + list(fn.args.kwonlyargs):
            params[a.arg] = a.annotation
        result: dict[str, Attribute] = {}
        for node in _walk_no_nested(fn):
            pairs: list[tuple[ast.expr, ast.expr | None, ast.expr | None]] = []
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Tuple) and isinstance(node.value, ast.Tuple) and len(t.elts) == len(node.value.elts):
                        pairs += [(tt, vv, None) for tt, vv in zip(t.elts, node.value.elts)]
                    elif isinstance(t, ast.Tuple):
                        pairs += [(tt, None, None) for tt in t.elts]
                    else:
                        pairs.append((t, node.value, None))
            elif isinstance(node, ast.AnnAssign):
                pairs.append((node.target, node.value, node.annotation))
            for target, value, ann in pairs:
                if not (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
                        and target.value.id == self_name):
                    continue
                name = target.attr
                if ann is not None:
                    _, _, vorigin = self._infer_value(value, params) if value is not None else (None, [], "annotated")
                    attr = Attribute(name=name, type=unparse(ann, 80), default=None, visibility=visibility(name),
                                     origin=vorigin if vorigin in ("created", "injected") else "annotated",
                                     lineno=node.lineno, refs=type_refs(ann))
                else:
                    type_str, refs, origin = self._infer_value(value, params) if value is not None else (None, [], "unknown")
                    attr = Attribute(name=name, type=type_str, visibility=visibility(name), origin=origin,
                                     lineno=node.lineno, refs=refs)
                if value is not None and not isinstance(value, ast.Name):
                    d = unparse(value, 50)
                    attr.default = d if method.name == "__init__" else None
                prev = result.get(name)
                if prev is None or (not prev.type and attr.type) or (prev.origin in ("unknown", "literal") and attr.origin in ("created", "injected")):
                    result[name] = attr
        return result

    def _infer_value(self, value: ast.expr | None, params: dict[str, ast.expr | None]) -> tuple[str | None, list[TypeRef], str]:
        """Infer ``(type, refs, origin)`` from an assigned expression."""
        if value is None:
            return None, [], "unknown"
        if isinstance(value, ast.Constant):
            if value.value is None:
                return None, [], "literal"
            return type(value.value).__name__, [], "literal"
        if isinstance(value, ast.Name):
            if value.id in params:
                ann = params[value.id]
                return unparse(ann, 80), type_refs(ann), "injected"
            return None, [], "unknown"
        if isinstance(value, ast.Call):
            func = dotted(value.func)
            if func is None:
                return None, [], "unknown"
            short = func.rsplit(".", 1)[-1]
            if short in LITERAL_FACTORIES:
                return short, [], "literal"
            if short[:1].isupper():
                return func, [TypeRef(func)], "created"
            # Alternate constructors: Config.load(...), Shape.from_json(...)
            if isinstance(value.func, ast.Attribute):
                owner = dotted(value.func.value)
                if owner and owner.rsplit(".", 1)[-1][:1].isupper():
                    return owner, [TypeRef(owner)], "created"
            return None, [], "unknown"
        if isinstance(value, (ast.List, ast.Set, ast.Tuple, ast.ListComp, ast.SetComp, ast.GeneratorExp)):
            kind = {ast.List: "list", ast.ListComp: "list", ast.Set: "set", ast.SetComp: "set",
                    ast.Tuple: "tuple", ast.GeneratorExp: "iterator"}[type(value)]
            elts = value.elts if hasattr(value, "elts") else [value.elt]
            refs: list[TypeRef] = []
            names: list[str] = []
            origin = "literal"
            for e in elts:
                t, r, o = self._infer_value(e, params)
                for ref in r:
                    refs.append(TypeRef(ref.name, "*"))
                if t and t not in names:
                    names.append(t)
                if o in ("created", "injected"):
                    origin = o
            if names and refs:
                return f"{kind}[{' | '.join(names[:3])}]", refs, origin
            return kind, [], "literal"
        if isinstance(value, (ast.Dict, ast.DictComp)):
            return "dict", [], "literal"
        if isinstance(value, (ast.IfExp, ast.BoolOp)):
            options = [value.body, value.orelse] if isinstance(value, ast.IfExp) else list(value.values)
            results = [self._infer_value(o, params) for o in options]
            typed = [r for r in results if r[1]]
            if typed:
                origin = "injected" if any(r[2] == "injected" for r in typed) else typed[0][2]
                return typed[0][0], typed[0][1], origin
            for r in results:
                if r[0]:
                    return r
            return None, [], "unknown"
        if isinstance(value, ast.Lambda):
            return "Callable", [], "literal"
        if isinstance(value, ast.JoinedStr):
            return "str", [], "literal"
        return None, [], "unknown"


# --------------------------------------------------------------------------- resolution

class Resolver:
    def __init__(self, project: Project):
        self.p = project
        self.by_short: dict[str, list[str]] = {}
        for cid, cls in project.classes.items():
            self.by_short.setdefault(cls.name, []).append(cid)

    def _follow(self, full: str, depth: int = 0) -> str | None:
        if full in self.p.classes:
            return full
        if depth > 6:
            return None
        mod_name, _, attr = full.rpartition(".")
        # module.attr where module re-exports attr
        while mod_name:
            mod = self.p.modules.get(mod_name)
            if mod is not None:
                first, _, rest = attr.partition(".")
                if first in mod.imports:
                    target = mod.imports[first] + (f".{rest}" if rest else "")
                    if target != full:
                        return self._follow(target, depth + 1)
                for star in filter(None, mod.imports.get("*", "").split(",")):
                    if (r := self._follow(f"{star}.{attr}", depth + 1)) is not None:
                        return r
                return None
            mod_name, _, head = mod_name.rpartition(".")
            attr = f"{head}.{attr}"
        return None

    def resolve(self, name: str | None, module: str, context: ClassInfo | None = None) -> str | None:
        if not name:
            return None
        name = name.strip().strip("'\"")
        if "[" in name:
            name = name.split("[", 1)[0]
        mod = self.p.modules.get(module)
        candidates = []
        if context is not None:
            candidates.append(f"{context.id}.{name}")
            if "." in context.qualname:  # sibling nested classes
                candidates.append(f"{context.id.rpartition('.')[0]}.{name}")
        candidates.append(f"{module}.{name}")
        for c in candidates:
            if c in self.p.classes:
                return c
        if mod is not None:
            first, _, rest = name.partition(".")
            if first in mod.imports:
                full = mod.imports[first] + (f".{rest}" if rest else "")
                if (r := self._follow(full)) is not None:
                    return r
                return None  # imported from outside the analysed package
            for star in filter(None, mod.imports.get("*", "").split(",")):
                if (r := self._follow(f"{star}.{name}")) is not None:
                    return r
        if (r := self._follow(name)) is not None:
            return r
        # Last resort: unique short name across the project.
        short = name.rsplit(".", 1)[-1]
        matches = self.by_short.get(short, [])
        if len(matches) == 1 and "." not in name:
            return matches[0]
        return None


STRENGTH = {"composition": 3, "aggregation": 2, "dependency": 1}


def build_relations(project: Project) -> None:
    resolver = Resolver(project)
    rels: dict[tuple[str, str, str], Relation] = {}
    assoc: dict[tuple[str, str], Relation] = {}

    def add_assoc(src: str, dst: str, kind: str, label: str | None, mult: str | None) -> None:
        key = (src, dst)
        cur = assoc.get(key)
        if cur is None or STRENGTH[kind] > STRENGTH[cur.kind]:
            labels = cur.label if cur is not None and cur.kind == kind else None
            assoc[key] = Relation(src, dst, kind, label if not labels else labels, mult)
        elif cur.kind == kind and label and kind != "dependency":
            existing = (cur.label or "").split(", ")
            if label not in existing:
                cur.label = ", ".join(filter(None, [cur.label, label]))
            if mult == "*" or cur.multiplicity is None:
                cur.multiplicity = mult

    for cls in project.classes.values():
        # inheritance
        cls.base_ids = []
        for raw in cls.bases:
            target = resolver.resolve(raw, cls.module, None)
            cls.base_ids.append(target)
            if target and target != cls.id:
                tgt = project.classes[target]
                kind = "realization" if "protocol" in tgt.stereotypes else "inheritance"
                rels[(cls.id, target, kind)] = Relation(cls.id, target, kind)
                if cls.id not in tgt.subclasses:
                    tgt.subclasses.append(cls.id)
        if cls.metaclass:
            meta = resolver.resolve(cls.metaclass, cls.module, None)
            if meta:
                add_assoc(cls.id, meta, "dependency", "«metaclass»", None)
        # attributes
        for attr in cls.attributes:
            if attr.kind == "enum_member":
                continue
            for ref in attr.refs:
                ref.target = resolver.resolve(ref.name, cls.module, cls)
                if not ref.target:
                    continue
                if attr.kind == "property":
                    add_assoc(cls.id, ref.target, "dependency", attr.name, ref.multiplicity)
                    continue
                if attr.origin == "created":
                    kind = "composition"
                elif attr.origin == "injected":
                    kind = "aggregation"
                elif cls.is_data:
                    kind = "composition"
                else:
                    kind = "aggregation"
                add_assoc(cls.id, ref.target, kind, attr.name, ref.multiplicity)
        # dependencies from signatures and instantiations
        for m in cls.methods:
            for ref in m.ref_names:
                ref.target = resolver.resolve(ref.name, cls.module, cls)
                if ref.target and ref.target != cls.id:
                    add_assoc(cls.id, ref.target, "dependency", None, None)
            for call in m.calls:
                head = call.split(".")[-1]
                if not head[:1].isupper() and "." not in call:
                    continue
                target = resolver.resolve(call, cls.module, cls)
                if target is None and "." in call:
                    target = resolver.resolve(call.rpartition(".")[0], cls.module, cls)
                if target and target != cls.id:
                    add_assoc(cls.id, target, "dependency", None, None)

    inherit_pairs = {(s, t) for (s, t, _k) in rels}
    project.relations = list(rels.values())
    for (s, t), r in assoc.items():
        if r.kind == "dependency" and ((s, t) in inherit_pairs or (t, s) in inherit_pairs):
            continue
        project.relations.append(r)

    # exception stereotype propagates down the hierarchy
    changed = True
    while changed:
        changed = False
        for cls in project.classes.values():
            if "exception" in cls.stereotypes:
                continue
            if any(b and "exception" in project.classes[b].stereotypes for b in cls.base_ids):
                cls.stereotypes.append("exception")
                changed = True


# --------------------------------------------------------------------------- entry point

def analyze(path: str | Path, exclude: Iterable[str] = (), name: str | None = None) -> Project:
    """Analyse a package directory (or single file) and return a :class:`Project`."""
    root = Path(path).resolve()
    if not root.exists():
        raise FileNotFoundError(f"No such file or directory: {root}")
    project = Project(name=name or root.stem, root=str(root))
    rel_base = root if root.is_dir() else root.parent
    analyzers = []
    for file, mod_name, is_pkg in discover(root, exclude):
        rel = file.relative_to(rel_base).as_posix()
        try:
            source = file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(file))
        except SyntaxError as exc:
            project.warnings.append(f"{rel}: syntax error at line {exc.lineno}: {exc.msg}")
            continue
        module = ModuleInfo(name=mod_name, file=rel, is_package=is_pkg)
        project.modules[mod_name] = module
        analyzers.append(ModuleAnalyzer(tree, module, rel))
    for a in analyzers:
        for cls in a.run():
            if cls.id in project.classes:
                project.warnings.append(f"{cls.file}:{cls.lineno}: duplicate class definition {cls.id}")
            project.classes[cls.id] = cls
    build_relations(project)
    from .patterns import detect_patterns

    detect_patterns(project)
    return project
