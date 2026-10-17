"""C++ front-end, built on the tree-sitter C++ grammar (no compiler, includes or build flags needed).

Pass 1 collects classes, structs, unions and enums (with namespaces, nesting and templates), their
members, type aliases and the out-of-line method definitions found in source files. Pass 2 resolves
names with C++ scoping rules, attaches out-of-line bodies to their declarations and analyses every
method body with knowledge of the class members, producing the same facts as the Python front-end.

Ownership is read from member types: values, ``std::unique_ptr`` and ``std::optional`` are owned
(composition); raw pointers, references, ``std::shared_ptr`` and ``std::weak_ptr`` are not
(aggregation). Whether a member is created by the class or injected is read from constructor
initialiser lists, default member initialisers and assignments.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from ..model import Attribute, ClassInfo, Method, ModuleInfo, Param, Project, TypeRef
from ..relations import QualifiedResolver
from . import add_path_module, source_files

SEQUENCES = {"vector", "list", "deque", "set", "unordered_set", "multiset", "unordered_multiset", "array",
             "forward_list", "queue", "stack", "priority_queue", "span", "valarray", "initializer_list",
             "QList", "QVector", "QSet", "QStack", "QQueue", "SmallVector", "flat_set"}
MAPPINGS = {"map", "unordered_map", "multimap", "unordered_multimap", "flat_map", "QMap", "QHash",
            "QMultiMap", "QMultiHash", "DenseMap", "StringMap"}
OWNING = {"unique_ptr", "optional", "scoped_ptr", "QScopedPointer", "auto_ptr"}
SHARED = {"shared_ptr", "QSharedPointer", "intrusive_ptr", "Rc", "Arc"}
NON_OWNING = {"weak_ptr", "QPointer", "QWeakPointer", "reference_wrapper", "observer_ptr", "not_null"}
CALLABLES = {"function", "move_only_function", "function_ref", "packaged_task"}
MAKERS = {"make_unique", "make_shared", "allocate_shared", "make_optional"}
PRIMITIVES = {"void", "bool", "char", "int", "short", "long", "float", "double", "unsigned", "signed", "auto",
              "size_t", "ssize_t", "string", "string_view", "wstring", "uint8_t", "uint16_t", "uint32_t",
              "uint64_t", "int8_t", "int16_t", "int32_t", "int64_t", "nullptr_t", "byte", "T"}
CLASS_NODES = {"class_specifier", "struct_specifier", "union_specifier"}
PREPROC = {"preproc_if", "preproc_ifdef", "preproc_else", "preproc_elif", "preproc_elifdef"}
# Macros that a preprocessor would remove but that confuse a grammar-based parser. They are blanked
# with spaces of the same length so byte offsets and line numbers are preserved.
_CLASS_HEAD_MACRO = re.compile(rb"\b(class|struct|union)(\s+)((?:(?:[A-Z][A-Z0-9_]{2,}|__declspec\s*\([^)]*\)|"
                               rb"__attribute__\s*\(\([^)]*\)\)|alignas\s*\([^)]*\))\s+)+)(?=[A-Za-z_])")
_LONE_MACRO = re.compile(rb"(?m)^[ \t]*[A-Z][A-Z0-9_]{2,}[ \t]*$")


def blank_macros(source: bytes) -> bytes:
    """``class LEVELDB_EXPORT DB {`` -> ``class                DB {``; drop lines holding only a macro (``Q_OBJECT``)."""
    def blank_head(m: re.Match) -> bytes:
        return m.group(1) + m.group(2) + re.sub(rb"[^\n]", b" ", m.group(3))
    source = _CLASS_HEAD_MACRO.sub(blank_head, source)
    return _LONE_MACRO.sub(lambda m: b" " * len(m.group(0)), source)


NOT_IMPLEMENTED = re.compile(r"not.?implemented|NotImplemented|unimplemented|logic_error", re.I)

_PARSER = None


def _parser():
    global _PARSER
    if _PARSER is None:
        try:
            import tree_sitter_cpp
            from tree_sitter import Language, Parser
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise RuntimeError("C++ support needs tree-sitter: pip install 'archlens[cpp]'") from exc
        _PARSER = Parser(Language(tree_sitter_cpp.language()))
    return _PARSER


def strip_args(name: str) -> str:
    """``ns::Foo<Bar<int>>::Inner`` -> ``ns::Foo::Inner``."""
    out, depth = [], 0
    for ch in name:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
    return "".join(out).replace(" ", "")


# --------------------------------------------------------------------------- pass 1 records

@dataclass
class PendingBody:
    method: Method
    body: object | None  # tree-sitter node: compound_statement
    inits: object | None  # field_initializer_list
    source: bytes = b""


@dataclass
class OutOfLine:
    class_path: str
    method: Method
    scopes: list[str]
    body: object
    inits: object | None
    source: bytes
    n_params: int


@dataclass
class FileState:
    module: ModuleInfo
    source: bytes
    using_namespaces: list[str] = field(default_factory=list)


class CppCollector:
    def __init__(self, project: Project):
        self.p = project
        self.qualified: dict[str, str] = {}  # "ns::Class" -> id
        self.aliases: dict[str, str] = {}
        self.scopes: dict[str, list[str]] = {}  # class id -> lookup scopes
        self.bodies: dict[str, list[PendingBody]] = {}
        self.out_of_line: list[OutOfLine] = []
        self.files: list[FileState] = []
        self.alias_types: dict[str, tuple[object, bytes]] = {}  # alias -> (aliased type node, source)
        self.trees: list = []  # keep parse trees alive while their nodes are referenced

    # -- helpers ------------------------------------------------------------
    def text(self, node, src: bytes) -> str:
        return src[node.start_byte:node.end_byte].decode("utf-8", "replace") if node is not None else ""

    def collect(self, file: FileState) -> None:
        tree = _parser().parse(file.source)
        self.trees.append(tree)
        self.files.append(file)
        self._walk(tree.root_node, file, ns=[], outer=None, template=False)

    def _walk(self, node, f: FileState, ns: list[str], outer: ClassInfo | None, template: bool) -> None:
        for child in node.named_children:
            self._decl(child, f, ns, outer, template)

    def _decl(self, node, f: FileState, ns: list[str], outer: ClassInfo | None, template: bool) -> None:
        t = node.type
        src = f.source
        if t == "namespace_definition":
            name = node.child_by_field_name("name")
            body = node.child_by_field_name("body")
            parts = [p for p in self.text(name, src).split("::") if p] if name is not None else []
            if body is not None:
                self._walk(body, f, ns + parts, outer, False)
        elif t == "template_declaration":
            for c in node.named_children:
                if c.type not in ("template_parameter_list",):
                    self._decl(c, f, ns, outer, True)
        elif t in CLASS_NODES:
            self._class(node, f, ns, outer, template)
        elif t == "enum_specifier":
            self._enum(node, f, ns, outer)
        elif t in ("declaration", "type_definition"):
            typ = node.child_by_field_name("type")
            if typ is not None and typ.type in CLASS_NODES:
                self._class(typ, f, ns, outer, template, typedef_name=self._typedef_name(node, src))
            elif typ is not None and typ.type == "enum_specifier":
                self._enum(typ, f, ns, outer)
            if t == "type_definition" and typ is not None:
                alias = self._typedef_name(node, src)
                if alias and typ.type not in CLASS_NODES:
                    self.aliases["::".join([*ns, alias])] = strip_args(self.text(typ, src))
        elif t == "alias_declaration":
            name = node.child_by_field_name("name")
            typ = node.child_by_field_name("type")
            if name is not None and typ is not None:
                key = "::".join([*ns, self.text(name, src)])
                self.aliases[key] = strip_args(self._type_core(typ, src))
                self.alias_types[key] = (typ, src)
        elif t == "function_definition":
            self._function_definition(node, f, ns)
        elif t == "linkage_specification":
            body = node.child_by_field_name("body")
            if body is not None:
                self._walk(body, f, ns, outer, template)
        elif t in PREPROC:
            self._walk(node, f, ns, outer, template)
        elif t == "using_declaration" and "namespace" in self.text(node, src).split()[:2]:
            target = self.text(node, src).split("namespace", 1)[1].strip(" ;")
            f.using_namespaces.append(target.lstrip(":"))

    def _typedef_name(self, node, src: bytes) -> str | None:
        for d in node.children_by_field_name("declarator"):
            if d.type == "type_identifier":
                return self.text(d, src)
        return None

    def _type_core(self, typ, src: bytes) -> str:
        if typ.type == "type_descriptor":
            inner = typ.child_by_field_name("type")
            return self.text(inner, src) if inner is not None else self.text(typ, src)
        return self.text(typ, src)

    # -- classes ------------------------------------------------------------
    def _class(self, node, f: FileState, ns: list[str], outer: ClassInfo | None, template: bool,
               typedef_name: str | None = None) -> ClassInfo | None:
        src = f.source
        body = node.child_by_field_name("body")
        name_node = node.child_by_field_name("name")
        if body is None:
            return None  # forward declaration
        written = strip_args(self.text(name_node, src)) if name_node is not None else typedef_name
        if not written:
            return None
        short = written.split("::")[-1]
        # ``struct Table::Rep { ... }`` defines a nested class out of line
        path = f"{outer.qualname}::{written}" if outer else written.lstrip(":")
        namespace = outer.namespace if outer else "::".join(ns)
        qualified = f"{namespace}::{path}" if namespace else path
        cid = f"{f.module.name}::{qualified}"
        kind = node.type.split("_")[0]
        cls = ClassInfo(id=cid, name=short, qualname=path, module=f.module.name, file=f.module.file,
                        lineno=node.start_point[0] + 1, end_lineno=node.end_point[0] + 1, language="cpp",
                        namespace=namespace or None)
        cls.docstring = self._doc_comment(node, src)
        if template:
            cls.stereotypes.append("template")
        if kind == "union":
            cls.stereotypes.append("union")
        for c in node.children:
            if c.type == "virtual_specifier" and self.text(c, src) == "final":
                cls.stereotypes.append("final")
            if c.type == "base_class_clause":
                for b in c.named_children:
                    if b.type in ("access_specifier", "virtual"):
                        continue
                    raw = self.text(b, src)
                    cls.bases.append(raw)
                    cls.base_args += self._refs_of_template_args(b, src)
        lower_bases = [strip_args(b).split("::")[-1].lower() for b in cls.bases]
        if any(b.endswith(("exception", "error")) for b in lower_bases):
            cls.stereotypes.append("exception")
        if qualified in self.qualified:
            self.p.warnings.append(f"{f.module.file}:{cls.lineno}: {qualified} is also defined in "
                                   f"{self.p.classes[self.qualified[qualified]].file}; keeping the first")
            return None
        self.qualified[qualified] = cid
        self.p.classes[cid] = cls
        f.module.classes.append(cid)
        self.scopes[cid] = self._scopes(namespace, path, f)
        self.bodies[cid] = []
        access = "private" if kind == "class" else "public"
        self._members(body, f, cls, access, template)
        self._finish_class(cls, kind)
        return cls

    def _scopes(self, namespace: str, path: str, f: FileState) -> list[str]:
        parts = (namespace.split("::") if namespace else []) + path.split("::")
        scopes = ["::".join(parts[:i]) for i in range(len(parts), 0, -1)]
        return scopes + [u for u in f.using_namespaces if u not in scopes]

    def _doc_comment(self, node, src: bytes) -> str | None:
        prev = node.prev_named_sibling
        if node.parent is not None and node.parent.type in ("template_declaration", "declaration"):
            prev = node.parent.prev_named_sibling
        lines = []
        while prev is not None and prev.type == "comment" and prev.end_point[0] >= node.start_point[0] - 1 - len(lines):
            lines.insert(0, self.text(prev, src))
            prev = prev.prev_named_sibling
        if not lines:
            return None
        text = "\n".join(lines)
        text = re.sub(r"^\s*(/\*\*?|\*/|\*|///?|//!?)\s?", "", text, flags=re.M).strip()
        text = re.sub(r"\*/\s*$", "", text).strip()
        return text or None

    def _members(self, body, f: FileState, cls: ClassInfo, access: str, template: bool) -> None:
        src = f.source
        for m in body.named_children:
            t = m.type
            if t == "access_specifier":
                access = self.text(m, src).strip(": ")
            elif t in PREPROC:
                self._members(m, f, cls, access, template)
            elif t == "template_declaration":
                for c in m.named_children:
                    if c.type in ("function_definition", "field_declaration", "declaration"):
                        self._member(c, f, cls, access)
                    elif c.type in CLASS_NODES:
                        self._class(c, f, [], cls, True)
            elif t in ("field_declaration", "declaration", "function_definition"):
                self._member(m, f, cls, access)
            elif t == "alias_declaration":
                name = m.child_by_field_name("name")
                typ = m.child_by_field_name("type")
                if name is not None and typ is not None:
                    key = f"{cls.namespace}::{cls.qualname}" if cls.namespace else cls.qualname
                    self.aliases[f"{key}::{self.text(name, src)}"] = strip_args(self._type_core(typ, src))
                    self.alias_types[f"{key}::{self.text(name, src)}"] = (typ, src)
            elif t in CLASS_NODES:
                self._class(m, f, [], cls, False)
            elif t == "enum_specifier":
                self._enum(m, f, [], cls)

    def _member(self, node, f: FileState, cls: ClassInfo, access: str) -> None:
        src = f.source
        typ = node.child_by_field_name("type")
        if typ is not None and typ.type in CLASS_NODES and typ.child_by_field_name("body") is not None:
            inner = self._class(typ, f, [], cls, False)
            if inner is None or not node.children_by_field_name("declarator"):
                return
        if typ is not None and typ.type == "enum_specifier" and typ.child_by_field_name("body") is not None:
            self._enum(typ, f, [], cls)
            if not node.children_by_field_name("declarator"):
                return
        declarators = node.children_by_field_name("declarator")
        func = next((fd for d in declarators if (fd := _function_declarator(d)) is not None), None)
        specifiers = {self.text(c, src) for c in node.children
                      if c.type in ("storage_class_specifier", "virtual", "explicit_function_specifier",
                                    "type_qualifier")}
        if "friend" in self.text(node, src).split()[:1]:
            return
        if func is not None:
            method = self._method(node, func, typ, declarators[0], f, cls, access, specifiers)
            if method is None:
                return
            cls.methods.append(method)
            if node.type == "function_definition":
                self.bodies[cls.id].append(PendingBody(method, node.child_by_field_name("body"),
                                                       _child_of_type(node, "field_initializer_list"), src))
            return
        if typ is None:
            return
        static = "static" in specifiers
        for d in declarators:
            name_node, ptr, ref, arr = _unwrap_declarator(d)
            if name_node is None:
                continue
            name = self.text(name_node, src)
            mult = "*" if arr else ("0..1" if ptr else "1")
            own = "reference" if (ptr or ref) else "owned"
            refs = self._type_refs(typ, src, mult, own)
            type_text = self.text(typ, src) + ("*" * ptr) + ("&" if ref else "") + ("[]" if arr else "")
            default = node.child_by_field_name("default_value")
            init_text = self.text(default, src) if default is not None else None
            attr = Attribute(name=name, type=" ".join(type_text.split())[:90], default=(init_text or None) and init_text[:50],
                             scope="class" if static else "instance", visibility=access, lineno=node.start_point[0] + 1,
                             refs=[r for r, _o in refs], ownership=_ownership([o for _r, o in refs]),
                             readonly="const" in specifiers or "constexpr" in specifiers)
            if default is not None:
                created = self._created_types(default, src)
                if created:
                    attr.origin = "created"
                elif default.type in ("number_literal", "string_literal", "true", "false", "nullptr"):
                    attr.origin = "literal"
            elif own == "owned" and refs:
                attr.origin = "created"  # a value member is constructed with its owner
            cls.attributes.append(attr)

    def _method(self, node, func, typ, top_decl, f: FileState, cls: ClassInfo | None, access: str,
                specifiers: set[str]) -> Method | None:
        src = f.source
        name_node = func.child_by_field_name("declarator")
        if name_node is None:
            return None
        raw = self.text(name_node, src)
        name = strip_args(raw).split("::")[-1]
        kind = "method"
        if name_node.type == "destructor_name" or name.startswith("~"):
            kind = "destructor"
        elif name_node.type == "operator_name" or name.startswith("operator"):
            kind = "operator"
        elif cls is not None and name == cls.name and typ is None:
            kind = "constructor"
        params = self._params(func.child_by_field_name("parameters"), src)
        ret = None
        if typ is not None:
            _, ptr, ref, _ = _unwrap_declarator(top_decl, stop_at_function=True)
            ret = " ".join(self.text(typ, src).split()) + "*" * ptr + ("&" if ref else "")
        trailing = _child_of_type(func, "trailing_return_type")
        if trailing is not None:
            ret = self.text(trailing, src).lstrip("-> ").strip()
        decos = [s for s in ("virtual", "static", "explicit", "inline", "constexpr") if s in specifiers]
        for c in func.children:
            if c.type == "virtual_specifier":
                decos.append(self.text(c, src))
            elif c.type == "type_qualifier":
                decos.append(self.text(c, src))
            elif c.type == "noexcept":
                decos.append("noexcept")
        pure = any(c.type == "number_literal" and self.text(c, src) == "0" for c in node.children) and \
            any(c.type == "=" for c in node.children)
        if _child_of_type(node, "delete_method_clause") is not None:
            decos.append("= delete")
        if _child_of_type(node, "default_method_clause") is not None:
            decos.append("= default")
        if pure:
            decos.append("= 0")
        m = Method(name=name, kind=kind, params=params, returns=ret, decorators=decos, visibility=access,
                   is_abstract=pure, is_static="static" in specifiers, lineno=node.start_point[0] + 1,
                   docstring=(self._doc_comment(node, src) or "").split("\n")[0] or None)
        body = node.child_by_field_name("body")
        m.is_stub = pure or (body is not None and _is_stub(body, src))
        if typ is not None:
            m.ref_names += [r for r, _o in self._type_refs(typ, src, "1", "owned")]
        for p in func.child_by_field_name("parameters").named_children if func.child_by_field_name("parameters") else []:
            ptyp = p.child_by_field_name("type")
            if ptyp is not None:
                m.ref_names += [r for r, _o in self._type_refs(ptyp, src, "1", "owned")]
        return m

    def _params(self, plist, src: bytes) -> list[Param]:
        out = []
        if plist is None:
            return out
        for p in plist.named_children:
            if p.type == "variadic_parameter":
                out.append(Param("...", kind="vararg"))
                continue
            if p.type not in ("parameter_declaration", "optional_parameter_declaration",
                              "variadic_parameter_declaration"):
                continue
            typ = p.child_by_field_name("type")
            decl = p.child_by_field_name("declarator")
            name_node, ptr, ref, arr = _unwrap_declarator(decl) if decl is not None else (None, 0, False, False)
            default = p.child_by_field_name("default_value")
            ann = " ".join((self.text(typ, src) if typ is not None else "").split()) + "*" * ptr + ("&" if ref else "")
            quals = [self.text(c, src) for c in p.children if c.type == "type_qualifier"]
            if quals:
                ann = " ".join(quals) + " " + ann
            out.append(Param(self.text(name_node, src) if name_node is not None else "", ann or None,
                             self.text(default, src)[:40] if default is not None else None,
                             kind="vararg" if p.type == "variadic_parameter_declaration" else "positional"))
        return out

    def _enum(self, node, f: FileState, ns: list[str], outer: ClassInfo | None) -> None:
        src = f.source
        name_node = node.child_by_field_name("name")
        body = node.child_by_field_name("body")
        if name_node is None or body is None:
            return
        short = self.text(name_node, src)
        path = f"{outer.qualname}::{short}" if outer else short
        namespace = outer.namespace if outer else "::".join(ns)
        qualified = f"{namespace}::{path}" if namespace else path
        cid = f"{f.module.name}::{qualified}"
        if qualified in self.qualified:
            return
        cls = ClassInfo(id=cid, name=short, qualname=path, module=f.module.name, file=f.module.file,
                        lineno=node.start_point[0] + 1, end_lineno=node.end_point[0] + 1, language="cpp",
                        namespace=namespace or None, stereotypes=["enum"], docstring=self._doc_comment(node, src))
        for e in body.named_children:
            if e.type == "enumerator":
                n = e.child_by_field_name("name")
                v = e.child_by_field_name("value")
                cls.attributes.append(Attribute(name=self.text(n, src), default=self.text(v, src) if v else None,
                                                scope="class", kind="enum_member", lineno=e.start_point[0] + 1))
        self.qualified[qualified] = cid
        self.p.classes[cid] = cls
        f.module.classes.append(cid)
        self.scopes[cid] = self._scopes(namespace, path, f)
        self.bodies[cid] = []

    def _finish_class(self, cls: ClassInfo, kind: str) -> None:
        if any(m.is_abstract for m in cls.methods):
            cls.stereotypes.append("abstract")
            cls.is_abstract = True
        fields = [a for a in cls.attributes if a.scope == "instance"]
        behaviour = [m for m in cls.methods if not m.special]
        if fields and not behaviour and all(a.visibility == "public" for a in fields) and not cls.bases:
            cls.stereotypes.append("struct")  # plain data structure

    def _function_definition(self, node, f: FileState, ns: list[str]) -> None:
        src = f.source
        decl = node.child_by_field_name("declarator")
        func = _function_declarator(decl) if decl is not None else None
        if func is None:
            return
        name_node = func.child_by_field_name("declarator")
        if name_node is None:
            return
        if name_node.type != "qualified_identifier":
            f.module.functions.append(self.text(name_node, src))
            return
        full = strip_args(self.text(name_node, src))
        class_path, _, _name = full.rpartition("::")
        typ = node.child_by_field_name("type")
        m = self._method(node, func, typ, decl, f, None, "public", set())
        if m is None:
            return
        if m.name == class_path.split("::")[-1]:
            m.kind = "constructor"
        scopes = ["::".join(ns[:i]) for i in range(len(ns), 0, -1)] + f.using_namespaces
        self.out_of_line.append(OutOfLine(class_path, m, scopes, node.child_by_field_name("body"),
                                          _child_of_type(node, "field_initializer_list"), src, len(m.params)))

    # -- types --------------------------------------------------------------
    def _refs_of_template_args(self, node, src: bytes) -> list[TypeRef]:
        args = _template_args(node)
        out = []
        for a in args:
            out += [r for r, _o in self._type_refs(a, src, "1", "owned")]
        return out

    def _type_refs(self, node, src: bytes, mult: str, own: str) -> list[tuple[TypeRef, str]]:
        """Class names referenced by a type, with multiplicity and ownership (owned/shared/reference)."""
        if node is None:
            return []
        if node.type == "type_descriptor":
            inner = node.child_by_field_name("type")
            decl = node.child_by_field_name("declarator")
            if decl is not None and decl.type.startswith("abstract_function"):
                return []
            if decl is not None and ("pointer" in decl.type or "reference" in decl.type):
                own = "reference"
                mult = "0..1" if mult == "1" and "pointer" in decl.type else mult
            return self._type_refs(inner, src, mult, own)
        if node.type in ("primitive_type", "sized_type_specifier", "placeholder_type_specifier", "auto"):
            return []
        base = _template_base(node, src)
        if base is None:
            return []
        short = base.split("::")[-1]
        args = _template_args(node)
        if short in SEQUENCES:
            return self._type_refs(args[0], src, "*", own) if args else []
        if short in MAPPINGS:
            return self._type_refs(args[1], src, "*", own) if len(args) > 1 else []
        if short in OWNING:
            return self._type_refs(args[0], src, "0..1" if short == "optional" and mult == "1" else mult,
                                   own if own == "reference" else "owned") if args else []
        if short in SHARED:
            return self._type_refs(args[0], src, mult, "shared") if args else []
        if short in NON_OWNING:
            return self._type_refs(args[0], src, mult, "reference") if args else []
        if short in CALLABLES:
            return []
        if short in ("variant", "tuple", "pair", "expected"):
            return [r for a in args for r in self._type_refs(a, src, mult, own)]
        if short in PRIMITIVES or base.startswith("std::"):
            return []
        out = [(TypeRef(base, mult), own)]
        for a in args:
            out += [(r, "reference") for r, _o in self._type_refs(a, src, mult, own)]
        return out

    def _created_types(self, node, src: bytes) -> list[str]:
        """Class names instantiated by an expression: new X, make_unique<X>(), X(...), X{...}."""
        out = []
        for n in _walk(node):
            if n.type == "new_expression":
                t = n.child_by_field_name("type")
                if t is not None:
                    out.append(strip_args(self.text(t, src)))
            elif n.type == "call_expression":
                fn = n.child_by_field_name("function")
                name = self.text(fn, src) if fn is not None else ""
                short = strip_args(name).split("::")[-1]
                if short in MAKERS:
                    for a in _template_args(_last_template(fn)):
                        out.append(strip_args(self._type_core(a, src)))
                elif fn is not None and fn.type in ("identifier", "qualified_identifier", "template_function") \
                        and short[:1].isupper():
                    out.append(strip_args(name))
            elif n.type == "compound_literal_expression":
                t = n.child_by_field_name("type")
                if t is not None:
                    out.append(strip_args(self.text(t, src)))
        return out

    # -- pass 2 -------------------------------------------------------------
    def resolve(self) -> None:
        resolver = QualifiedResolver(self.qualified, self.aliases)
        classes = {cid: self.p.classes[cid] for cid in self.qualified.values()}
        for cid, cls in classes.items():
            scopes = self.scopes[cid]
            outer_scopes = scopes[1:]  # bases are looked up from the enclosing scope
            cls.base_ids = [resolver.resolve(strip_args(b), outer_scopes) for b in cls.bases]
            for ref in cls.base_args:
                ref.target = resolver.resolve(strip_args(ref.name), scopes)
            for a in cls.attributes:
                self._expand_aliases(a, scopes)
                for ref in a.refs:
                    ref.target = resolver.resolve(strip_args(ref.name), scopes)
            for m in cls.methods:
                for ref in m.ref_names:
                    ref.target = resolver.resolve(strip_args(ref.name), scopes)
        # attach out-of-line definitions to their declarations (overloads matched by parameter count)
        with_body = {id(p.method) for bodies in self.bodies.values() for p in bodies}
        for d in self.out_of_line:
            cid = resolver.resolve(d.class_path, d.scopes)
            if cid is None:
                continue
            cls = classes[cid]
            candidates = [m for m in cls.methods if m.name == d.method.name]
            free = [m for m in candidates if id(m) not in with_body]
            target = next((m for m in free if len(m.params) == d.n_params), None) or (free or candidates or [None])[0]
            if target is None:
                d.method.visibility = "private"
                cls.methods.append(d.method)
                target = d.method
            else:
                target.is_stub = d.method.is_stub
                if not target.params and d.method.params:
                    target.params = d.method.params
            self.bodies[cid].append(PendingBody(target, d.body, d.inits, d.source))
            with_body.add(id(target))
            for ref in d.method.ref_names:
                ref.target = resolver.resolve(strip_args(ref.name), self.scopes[cid])
                if ref.target and ref not in target.ref_names:
                    target.ref_names.append(ref)
        # bodies
        children: dict[str, list[str]] = {}
        for cid, cls in classes.items():
            for b in filter(None, cls.base_ids):
                children.setdefault(b, []).append(cid)
        for cid, cls in classes.items():
            lineage = _ancestors(cid, classes)
            members = {a.name: a for c in [cid, *lineage] for a in classes[c].attributes if a.kind != "enum_member"}
            methods = {m.name for c in [cid, *lineage] for m in classes[c].methods}
            for pending in self.bodies[cid]:
                BodyAnalyzer(self, cls, pending, members, methods, resolver, self.scopes[cid]).run()

    def _expand_aliases(self, attr: Attribute, scopes: list[str]) -> None:
        """Replace references to type aliases (``using Ptr = std::shared_ptr<T>``) by the aliased type's refs."""
        refs, owns = [], []
        for ref in attr.refs:
            alias = next((f"{sc}::{ref.name}" if sc else ref.name for sc in [*scopes, ""]
                          if (f"{sc}::{ref.name}" if sc else ref.name) in self.alias_types), None)
            if alias is None:
                refs.append(ref)
                continue
            node, src = self.alias_types[alias]
            core = node.child_by_field_name("type") if node.type == "type_descriptor" else node
            expanded = self._type_refs(node if node.type == "type_descriptor" else core, src, ref.multiplicity,
                                       attr.ownership or "owned")
            refs += [r for r, _o in expanded]
            owns += [o for _r, o in expanded]
        if owns:
            attr.ownership = _ownership(owns) if attr.ownership in (None, "owned") else attr.ownership
        attr.refs = refs

    def finish(self) -> None:
        for cls in (self.p.classes[c] for c in self.qualified.values()):
            if cls.is_abstract and "abstract" not in cls.stereotypes:
                cls.stereotypes.append("abstract")


def _ancestors(cid: str, classes: dict[str, ClassInfo]) -> list[str]:
    out, stack = [], list(filter(None, classes[cid].base_ids))
    while stack:
        c = stack.pop()
        if c in classes and c not in out and c != cid:
            out.append(c)
            stack.extend(filter(None, classes[c].base_ids))
    return out


# --------------------------------------------------------------------------- method bodies

class BodyAnalyzer:
    def __init__(self, col: CppCollector, cls: ClassInfo, pending: PendingBody, members: dict[str, Attribute],
                 methods: set[str], resolver: QualifiedResolver, scopes: list[str]):
        self.col, self.cls, self.m = col, cls, pending.method
        self.body, self.inits, self.src = pending.body, pending.inits, pending.source
        self.members, self.methods, self.resolver, self.scopes = members, methods, resolver, scopes
        self.params = {p.name for p in self.m.params}
        self.statics = {n for n, a in members.items() if a.scope == "class"}

    def t(self, node) -> str:
        return self.col.text(node, self.src)

    def member_of(self, node) -> str | None:
        """Member named by ``x_`` or ``this->x_`` (or ``self.x_``-like chains)."""
        if node is None:
            return None
        if node.type in ("identifier", "field_identifier") and self.t(node) in self.members:
            return self.t(node)
        if node.type == "field_expression":
            arg = node.child_by_field_name("argument")
            if arg is not None and arg.type == "this":
                name = self.t(node.child_by_field_name("field"))
                return name if name in self.members else None
        if node.type == "qualified_identifier":
            name = self.t(node).split("::")[-1]
            return name if name in self.statics else None
        return None

    def note_call(self, name: str) -> None:
        clean = strip_args(name)
        if clean and clean not in self.m.calls:
            self.m.calls.append(clean)
        target = self.resolver.resolve(clean, self.scopes)
        if target:
            self.m.call_targets[clean] = target

    def origin_of(self, value) -> tuple[str | None, list[str]]:
        created = self.col._created_types(value, self.src)
        if created:
            return "created", created
        core = value
        while core is not None and core.type == "call_expression" and \
                strip_args(self.t(core.child_by_field_name("function"))).split("::")[-1] in ("move", "forward"):
            args = core.child_by_field_name("arguments")
            core = args.named_children[0] if args is not None and args.named_children else None
        if core is not None and core.type == "identifier" and self.t(core) in self.params:
            return "injected", []
        return None, []

    def set_origin(self, member: str, value) -> None:
        attr = self.members.get(member)
        if attr is None or value is None:
            return
        origin, created = self.origin_of(value)
        if origin == "injected" and (self.m.kind == "constructor" or attr.origin in ("unknown", "annotated", "literal")):
            attr.origin = "injected"
        elif origin == "created" and attr.origin != "injected":
            attr.origin = "created"
            if not attr.refs:
                attr.refs = [TypeRef(c) for c in created[:1]]
                for ref in attr.refs:
                    ref.target = self.resolver.resolve(ref.name, self.scopes)

    def run(self) -> None:
        m = self.m
        loop_vars: dict[str, str] = {}
        if self.inits is not None:
            for fi in self.inits.named_children:
                if fi.type != "field_initializer":
                    continue
                name_node = next((c for c in fi.named_children if c.type in ("field_identifier", "identifier")), None)
                args = next((c for c in fi.named_children if c.type in ("argument_list", "initializer_list")), None)
                if name_node is not None and args is not None and args.named_children:
                    self.set_origin(self.t(name_node), args.named_children[0])
                for c in _walk(fi):
                    if c.type == "call_expression":
                        self.visit_call(c, loop_vars)
        if self.body is None:
            return
        for node in _walk(self.body):
            t = node.type
            if t == "return_statement":
                val = node.named_children[0] if node.named_children else None
                if val is not None and (val.type == "this" or (val.type == "pointer_expression" and self.t(val).replace(" ", "") == "*this")):
                    m.returns_self = True
            elif t == "throw_statement" and NOT_IMPLEMENTED.search(self.t(node)):
                m.raises_not_implemented = True
            elif t == "for_range_loop":
                right = node.child_by_field_name("right")
                src_member = self.member_of(right) if right is not None else None
                if src_member is None and right is not None and right.type == "call_expression":
                    fn = right.child_by_field_name("function")
                    if fn is not None and fn.type == "field_expression":
                        src_member = self.member_of(fn.child_by_field_name("argument"))
                if src_member:
                    _add(m.iterated_attrs, src_member)
                    decl = node.child_by_field_name("declarator")
                    name_node = _unwrap_declarator(decl)[0] if decl is not None else None
                    if name_node is not None:
                        loop_vars[self.t(name_node)] = src_member
            elif t == "call_expression":
                self.visit_call(node, loop_vars)
            elif t == "new_expression":
                typ = node.child_by_field_name("type")
                if typ is not None:
                    self.note_call(self.t(typ))
            elif t == "assignment_expression":
                left = node.child_by_field_name("left")
                right = node.child_by_field_name("right")
                base = left.child_by_field_name("argument") if left is not None and left.type == "subscript_expression" else left
                member = self.member_of(base)
                if member:
                    _add(m.attr_writes, member)
                    if left is base:
                        self.set_origin(member, right)
                    if member in self.statics:
                        _add(m.class_attr_refs, member)
            elif t == "declaration" and any(c.type == "storage_class_specifier" and self.t(c) == "static" for c in node.children):
                typ = node.child_by_field_name("type")
                if typ is not None and strip_args(self.t(typ)).split("::")[-1] == self.cls.name:
                    _add(m.class_attr_refs, "<static local instance>")
            elif t in ("identifier", "qualified_identifier") and node.parent is not None and node.parent.type != "qualified_identifier":
                name = self.t(node).split("::")[-1]
                if name in self.statics:
                    _add(m.class_attr_refs, name)
        for var, src_member in loop_vars.items():
            if var in m.name_calls:
                m.attr_calls.setdefault(src_member, [])
                for call in m.name_calls[var]:
                    _add(m.attr_calls[src_member], call)

    def visit_call(self, node, loop_vars: dict[str, str]) -> None:
        m = self.m
        fn = node.child_by_field_name("function")
        if fn is None:
            return
        ft = fn.type
        if ft == "identifier":
            name = self.t(fn)
            if name in self.members:
                m.attr_calls.setdefault(name, [])
                _add(m.attr_calls[name], "__call__")
            elif name in self.methods:
                _add(m.self_calls, name)
            elif name in loop_vars:
                m.name_calls.setdefault(name, [])
                _add(m.name_calls[name], "__call__")
            else:
                self.note_call(name)
        elif ft == "field_expression":
            arg = fn.child_by_field_name("argument")
            field_name = self.t(fn.child_by_field_name("field"))
            while arg is not None and arg.type in ("parenthesized_expression", "pointer_expression") and arg.named_children:
                arg = arg.named_children[-1]
            if arg is None:
                return
            member = self.member_of(arg)
            if arg.type == "this":
                _add(m.self_calls, field_name)
            elif member:
                m.attr_calls.setdefault(member, [])
                _add(m.attr_calls[member], field_name)
                if field_name in ("begin", "cbegin", "rbegin"):
                    _add(m.iterated_attrs, member)
            elif arg.type == "identifier":
                var = self.t(arg)
                m.name_calls.setdefault(var, [])
                _add(m.name_calls[var], field_name)
            elif arg.type == "call_expression":  # e.g. load()->read()
                inner = arg.child_by_field_name("function")
                if inner is not None and inner.type == "identifier" and self.t(inner) in self.methods:
                    _add(m.self_calls, self.t(inner))
        elif ft in ("qualified_identifier", "template_function"):
            name = strip_args(self.t(fn))
            short = name.split("::")[-1]
            if short in MAKERS:
                for a in _template_args(_last_template(fn)):
                    self.note_call(self.col._type_core(a, self.src))
            elif short in ("move", "forward", "static_cast", "dynamic_cast"):
                pass
            elif short in self.methods and "::" in name and \
                    self.resolver.resolve(name.rpartition("::")[0], self.scopes) in (self.cls.id, *self.cls.base_ids):
                _add(m.self_calls, short)  # Base::method() or Self::method()
            else:
                self.note_call(name)
                owner = name.rpartition("::")[0]
                if owner:
                    target = self.resolver.resolve(owner, self.scopes)
                    if target:
                        m.call_targets[owner] = target
        elif ft in ("subscript_expression", "call_expression"):
            # creator looked up in a table: registry_[name]() or registry_.at(name)()
            inner = fn.child_by_field_name("function") if ft == "call_expression" else None
            lookup = inner is not None and inner.type == "field_expression" and \
                self.t(inner.child_by_field_name("field")) in ("at", "find", "get", "lookup", "value")
            if ft == "subscript_expression" or lookup:
                m.dynamic_instantiation = True
            base = fn.child_by_field_name("argument") if ft == "subscript_expression" else \
                inner.child_by_field_name("argument") if lookup else None
            member = self.member_of(base)
            if member:
                m.attr_calls.setdefault(member, [])
                _add(m.attr_calls[member], "__getitem__")


# --------------------------------------------------------------------------- tree helpers

def _walk(node) -> Iterator:
    stack = [node]
    while stack:
        cur = stack.pop()
        yield cur
        if cur.type in ("lambda_expression",) and cur is not node:
            continue
        stack.extend(reversed(cur.named_children))


def _child_of_type(node, type_name: str):
    for c in node.children:
        if c.type == type_name:
            return c
    return None


def _function_declarator(decl):
    while decl is not None:
        if decl.type == "function_declarator":
            return decl
        if decl.type in ("pointer_declarator", "reference_declarator", "init_declarator", "attributed_declarator",
                         "parenthesized_declarator"):
            decl = decl.child_by_field_name("declarator") or (decl.named_children[-1] if decl.named_children else None)
            continue
        return None
    return None


def _unwrap_declarator(decl, stop_at_function: bool = False):
    """Return ``(name_node, pointer_depth, is_reference, is_array)`` for a (possibly nested) declarator."""
    ptr, ref, arr = 0, False, False
    while decl is not None:
        t = decl.type
        if t in ("identifier", "field_identifier", "type_identifier", "destructor_name", "operator_name"):
            return decl, ptr, ref, arr
        if t == "function_declarator":
            return (None, ptr, ref, arr) if stop_at_function else (decl.child_by_field_name("declarator"), ptr, ref, arr)
        if t == "pointer_declarator":
            ptr += 1
        elif t == "reference_declarator":
            ref = True
        elif t == "array_declarator":
            arr = True
        elif t == "structured_binding_declarator":
            return (decl.named_children[0] if decl.named_children else None), ptr, ref, arr
        nxt = decl.child_by_field_name("declarator")
        if nxt is None:
            nxt = next((c for c in decl.named_children if c.type not in ("type_qualifier", "ms_pointer_modifier")), None)
        decl = nxt
    return None, ptr, ref, arr


def _last_template(node):
    """The template_type/template_function at the end of a qualified name."""
    while node is not None and node.type == "qualified_identifier":
        node = node.child_by_field_name("name")
    return node


def _template_base(node, src: bytes) -> str | None:
    if node.type in ("type_identifier", "identifier", "namespace_identifier"):
        return src[node.start_byte:node.end_byte].decode()
    if node.type in ("qualified_identifier", "template_type", "dependent_type", "template_function"):
        return strip_args(src[node.start_byte:node.end_byte].decode())
    return None


def _template_args(node) -> list:
    last = _last_template(node)
    if last is None or last.type not in ("template_type", "template_function"):
        return []
    args = last.child_by_field_name("arguments")
    return [a for a in args.named_children if a.type in ("type_descriptor",)] if args is not None else []


def _ownership(owns: list[str]) -> str | None:
    if not owns:
        return None
    if "owned" in owns:
        return "owned"
    return "shared" if "shared" in owns else "reference"


def _is_stub(body, src: bytes) -> bool:
    stmts = [c for c in body.named_children if c.type != "comment"]
    if not stmts:
        return True
    return all(s.type == "throw_statement" or (s.type == "return_statement" and len(s.named_children) <= 1
                                                and (not s.named_children or s.named_children[0].type in
                                                     ("number_literal", "true", "false", "nullptr", "string_literal")))
               for s in stmts)


def _add(lst: list[str], value: str) -> None:
    if value not in lst:
        lst.append(value)


# --------------------------------------------------------------------------- entry point

def analyze_cpp(root: Path, project: Project, exclude: Iterable[str] = ()) -> None:
    col = CppCollector(project)
    # headers first so that declarations win over definitions in sources
    files = sorted(source_files(root, "cpp", exclude), key=lambda f: (not f.suffix.lower().startswith(".h"), str(f)))
    for f in files:
        module = add_path_module(project, root, f, "cpp")
        try:
            source = f.read_bytes()
        except OSError as exc:
            project.warnings.append(f"{module.file}: cannot read ({exc})")
            continue
        col.collect(FileState(module, blank_macros(source)))
    col.resolve()
    col.finish()
