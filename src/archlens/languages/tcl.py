"""Tcl front-end for TclOO classes (``oo::class``, ``oo::define``, ``oo::abstract``, ``oo::singleton``).

The source is parsed with a small Tcl parser that follows the language's own rules (words, braces,
quotes, ``[command substitution]``, ``{*}``, comments and line continuations); nothing is evaluated.

Tcl is untyped, so relations are inferred:

* ``set obj [Shape new]`` / ``[Shape create name]`` makes ``obj`` a Shape created by the class
  (composition);
* ``set obj $param`` in a constructor makes it an injected collaborator (aggregation). Its class
  is read from type checks (``info object isa typeof $p Cls``), from a parameter or variable name
  that matches a class name (``sortStrategy`` -> ``SortStrategy``), or from *usage*: the methods
  called on it (``$obj sort ...``) narrowed to the single class family that defines them all.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from ..model import Attribute, ClassInfo, Method, ModuleInfo, Param, Project, TypeRef
from ..relations import QualifiedResolver
from . import add_path_module, source_files

CLASS_CREATORS = {"oo::class": None, "oo::abstract": "abstract", "oo::singleton": "singleton"}
NOT_IMPLEMENTED = re.compile(r"abstract|not\s+implemented|must\s+be\s+(overridden|implemented)|subclass\w*\s+must|"
                             r"unimplemented|override", re.I)
LIST_OPS = {"lappend": "lappend", "lset": "lset", "linsert": "insert", "lremove": "remove"}
DEFINITION_COMMANDS = re.compile(r"(?m)^\s*(superclass|method|constructor|destructor|variable|mixin|class_method)\b")
CONTROL_BODIES = {"while", "for", "foreach", "lmap", "catch", "try", "time", "eval", "uplevel", "if", "switch", "dict"}


# --------------------------------------------------------------------------- Tcl parsing

@dataclass
class Word:
    text: str
    kind: str  # brace | quote | bare
    line: int
    expand: bool = False


@dataclass
class Command:
    words: list[Word]
    line: int

    @property
    def name(self) -> str:
        return self.words[0].text if self.words else ""

    def arg(self, i: int) -> str | None:
        return self.words[i].text if len(self.words) > i else None


def _match_brace(src: str, i: int) -> int:
    depth, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def _match_bracket(src: str, i: int) -> int:
    depth, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == "\\":
            i += 2
            continue
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return i + 1
        elif c == "{" and depth >= 1 and (i == 0 or src[i - 1] in " \t\n["):
            i = _match_brace(src, i)
            continue
        elif c == '"' and depth >= 1 and (i == 0 or src[i - 1] in " \t\n["):
            i = _match_quote(src, i)
            continue
        i += 1
    return n


def _match_quote(src: str, i: int) -> int:
    n = len(src)
    i += 1
    while i < n:
        c = src[i]
        if c == "\\":
            i += 2
            continue
        if c == "[":
            i = _match_bracket(src, i)
            continue
        if c == '"':
            return i + 1
        i += 1
    return n


def _scan_bare(src: str, i: int, stop: str) -> int:
    n = len(src)
    while i < n:
        c = src[i]
        if c == "\\":
            i += 2
            continue
        if c in " \t" or c in stop:
            return i
        if c == "[":
            i = _match_bracket(src, i)
            continue
        i += 1
    return n


def parse_script(src: str, line: int = 1) -> list[Command]:
    """Split a Tcl script into commands and words, keeping line numbers."""
    cmds: list[Command] = []
    i, n = 0, len(src)
    while i < n:
        while i < n and (src[i] in " \t\r\n;" or src.startswith("\\\n", i)):
            if src[i] == "\n":
                line += 1
            i += 2 if src.startswith("\\\n", i) else 1
        if i >= n:
            break
        if src[i] == "#":
            while i < n and src[i] != "\n":
                if src[i] == "\\" and i + 1 < n and src[i + 1] == "\n":
                    line += 1
                    i += 2
                    continue
                i += 1
            continue
        words, cmd_line = [], line
        while i < n:
            while i < n and (src[i] in " \t\r" or src.startswith("\\\n", i)):
                if src[i] == "\\":
                    line += 1
                    i += 2
                else:
                    i += 1
            if i >= n or src[i] in "\n;":
                break
            expand = False
            if src.startswith("{*}", i) and i + 3 < n and src[i + 3] not in " \t\r\n;":
                expand, i = True, i + 3
            start, wline = i, line
            if src[i] == "{":
                j = _match_brace(src, i)
                word = Word(src[i + 1:j - 1], "brace", wline, expand)
            elif src[i] == '"':
                j = _match_quote(src, i)
                word = Word(src[i + 1:j - 1], "quote", wline, expand)
            else:
                j = _scan_bare(src, i, "\n;")
                word = Word(src[i:j], "bare", wline, expand)
            line += src.count("\n", start, j)
            words.append(word)
            i = j
        if words:
            cmds.append(Command(words, cmd_line))
    return cmds


def parse_list(text: str) -> list[str]:
    """Elements of a Tcl list (brace/quote grouping, whitespace separated)."""
    out, i, n = [], 0, len(text)
    while i < n:
        while i < n and text[i] in " \t\r\n":
            i += 1
        if i >= n:
            break
        if text[i] == "{":
            j = _match_brace(text, i)
            out.append(text[i + 1:j - 1])
        elif text[i] == '"':
            j = _match_quote(text, i)
            out.append(text[i + 1:j - 1])
        else:
            j = _scan_bare(text, i, "\n")
            out.append(text[i:j])
        i = j
    return out


def substitutions(word: Word) -> list[str]:
    """Scripts inside ``[...]`` in a quoted or bare word (braced words are literal)."""
    if word.kind == "brace":
        return []
    out, text, i = [], word.text, 0
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == "[":
            j = _match_bracket(text, i)
            out.append(text[i + 1:j - 1])
            i = j
            continue
        i += 1
    return out


def _single_command(text: str) -> Command | None:
    """Parse ``[Foo new ...]``-style text (with or without the brackets) into one command."""
    text = text.strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    cmds = parse_script(text)
    return cmds[0] if len(cmds) == 1 else None


# --------------------------------------------------------------------------- TclOO model building

@dataclass
class ClassDef:
    name: str  # fully qualified, without leading ::
    module: ModuleInfo
    line: int
    creator: str
    namespace: str
    doc: str | None = None


@dataclass
class Definition:
    cls: str  # fully qualified target class name
    commands: list[Command]
    namespace: str
    module: ModuleInfo


@dataclass
class PendingMethod:
    method: Method
    body: str
    line: int
    namespace: str


@dataclass
class TclState:
    classes: dict[str, ClassInfo] = field(default_factory=dict)  # qualified -> class
    defs: list[ClassDef] = field(default_factory=list)
    definitions: list[Definition] = field(default_factory=list)
    metaclasses: set[str] = field(default_factory=lambda: set(CLASS_CREATORS))
    bodies: dict[str, list[PendingMethod]] = field(default_factory=dict)
    mixins: set[str] = field(default_factory=set)
    from_params: set[tuple[str, str]] = field(default_factory=set)  # (class id, variable) assigned from a parameter


def _qualify(name: str, namespace: str) -> str:
    if name.startswith("::"):
        return name.lstrip(":")
    return f"{namespace}::{name}" if namespace else name


def _doc_before(lines: list[str], line: int) -> str | None:
    out, i = [], line - 2
    while 0 <= i < len(lines) and lines[i].strip().startswith("#"):
        out.insert(0, lines[i].strip().lstrip("#").strip())
        i -= 1
    return "\n".join(out).strip() or None


def _scan_file(state: TclState, script: list[Command], module: ModuleInfo, namespace: str, lines: list[str]) -> None:
    for cmd in script:
        name = cmd.name.lstrip(":") if cmd.name.startswith("::oo::") else cmd.name
        if name == "namespace" and cmd.arg(1) == "eval" and len(cmd.words) >= 4:
            ns = _qualify(cmd.arg(2), namespace)
            _scan_file(state, parse_script(cmd.words[3].text, cmd.words[3].line), module, ns, lines)
        elif (name in state.metaclasses or _qualify(name, namespace) in state.metaclasses) and cmd.arg(1) == "create" \
                and len(cmd.words) >= 3:
            qname = _qualify(cmd.arg(2), namespace)
            creator = name if name in CLASS_CREATORS else _qualify(name, namespace)
            state.defs.append(ClassDef(qname, module, cmd.line, creator, namespace, _doc_before(lines, cmd.line)))
            if len(cmd.words) >= 4:
                body = parse_script(cmd.words[3].text, cmd.words[3].line)
                state.definitions.append(Definition(qname, body, namespace, module))
                if any(c.name == "superclass" and any(w.text.lstrip(":") in state.metaclasses for w in c.words[1:])
                       for c in body):
                    state.metaclasses.add(qname)
        elif name.endswith("::define") and name.lstrip(":") != "oo::define" and len(cmd.words) == 3 \
                and cmd.words[2].kind == "brace" and DEFINITION_COMMANDS.search(cmd.words[2].text):
            # TclOO dialects such as clay::define / oo::dialect: create-or-extend a class from a definition body
            qname = _qualify(cmd.arg(1), namespace)
            state.defs.append(ClassDef(qname, module, cmd.line, "dialect:" + name.lstrip(":"), namespace,
                                       _doc_before(lines, cmd.line)))
            state.definitions.append(Definition(qname, parse_script(cmd.words[2].text, cmd.words[2].line),
                                                namespace, module))
        elif name in ("oo::define", "define") and len(cmd.words) >= 3:
            qname = _qualify(cmd.arg(1), namespace)
            if len(cmd.words) == 3:
                body = parse_script(cmd.words[2].text, cmd.words[2].line)
            else:
                body = [Command(cmd.words[2:], cmd.line)]
            state.definitions.append(Definition(qname, body, namespace, module))
        elif name == "proc" and len(cmd.words) >= 4:
            module.functions.append(cmd.arg(1))
        elif name in ("if", "catch") and len(cmd.words) >= 2:
            for w in cmd.words[1:]:
                if w.kind == "brace" and ("oo::" in w.text or "namespace" in w.text):
                    _scan_file(state, parse_script(w.text, w.line), module, namespace, lines)


def _visibility(name: str) -> str:
    return "public" if name[:1].islower() else "protected"


def _params(spec: str) -> list[Param]:
    out = []
    for item in parse_list(spec):
        parts = parse_list(item)
        if not parts:
            continue
        pname = parts[0]
        if pname == "args":
            out.append(Param("args", kind="vararg"))
        else:
            out.append(Param(pname, default=parts[1][:40] if len(parts) > 1 else None))
    return out


def _apply_definition(state: TclState, cls: ClassInfo, cmds: list[Command], namespace: str, *, private: bool = False,
                      class_level: bool = False) -> None:
    pending = state.bodies.setdefault(cls.id, [])
    for cmd in cmds:
        w = cmd.words
        name = cmd.name
        if name in ("superclass", "mixin"):
            args = [x.text for x in w[1:] if not x.text.startswith("-")]
            names = [n for a in args for n in parse_list(a)]
            for b in names:
                if b.lstrip(":") in ("oo::class", "oo::object"):
                    if b.lstrip(":") == "oo::class":
                        cls.stereotypes.append("metaclass")
                    continue
                cls.bases.append(b)
                if name == "mixin":
                    state.mixins.add(_qualify(b, namespace))
        elif name == "variable" or (name == "private" and len(w) > 1 and w[1].text == "variable"):
            vis = "private" if (private or name == "private") else "protected"
            for v in w[(2 if name == "private" else 1):]:
                if v.text.startswith("-"):
                    continue
                for vname in parse_list(v.text):
                    if cls.attribute(vname) is None:
                        cls.attributes.append(Attribute(name=vname, scope="class" if class_level else "instance",
                                                        visibility=vis, lineno=cmd.line))
        elif name == "property" and len(w) >= 2:
            cls.attributes.append(Attribute(name=w[1].text, kind="property", visibility="public", lineno=cmd.line,
                                            readonly="-kind readable" in " ".join(x.text for x in w)))
        elif name in ("method", "classmethod", "class_method") or (name == "private" and len(w) > 2 and w[1].text == "method"):
            rest = w[2:] if name == "private" else w[1:]
            opts = [x.text for x in rest if x.text in ("-export", "-unexport", "-private")]
            rest = [x for x in rest if x.text not in ("-export", "-unexport", "-private")]
            if len(rest) < 3:
                continue
            mname = rest[0].text
            vis = "private" if (private or name == "private" or "-private" in opts) else \
                "public" if "-export" in opts else "protected" if "-unexport" in opts else _visibility(mname)
            m = Method(name=mname, params=_params(rest[1].text), visibility=vis, lineno=cmd.line,
                       is_classmethod=class_level or name in ("classmethod", "class_method"))
            _replace_method(cls, m)
            pending.append(PendingMethod(m, rest[2].text, rest[2].line, namespace))
        elif name == "constructor" and len(w) >= 3:
            m = Method(name="constructor", kind="constructor", params=_params(w[1].text), visibility="public",
                       lineno=cmd.line)
            _replace_method(cls, m)
            pending.append(PendingMethod(m, w[2].text, w[2].line, namespace))
        elif name == "destructor" and len(w) >= 2:
            m = Method(name="destructor", kind="destructor", visibility="public", lineno=cmd.line)
            _replace_method(cls, m)
            pending.append(PendingMethod(m, w[1].text, w[1].line, namespace))
        elif name == "forward" and len(w) >= 3:
            m = Method(name=w[1].text, visibility=_visibility(w[1].text), lineno=cmd.line,
                       decorators=["forward " + " ".join(x.text for x in w[2:])])
            target = w[2].text
            if target == "my" and len(w) > 3:
                m.self_calls.append(w[3].text)
            else:
                m.calls.append(target)
                if len(w) > 3:
                    m.attr_calls.setdefault(target, []).append(w[3].text)
            _replace_method(cls, m)
        elif name in ("export", "unexport"):
            for x in w[1:]:
                for mname in parse_list(x.text):
                    meth = cls.method(mname)
                    if meth is not None:
                        meth.visibility = "public" if name == "export" else "protected"
        elif name == "private" and len(w) == 2:
            _apply_definition(state, cls, parse_script(w[1].text, w[1].line), namespace, private=True,
                              class_level=class_level)
        elif name == "self" and len(w) >= 2:
            if len(w) == 2:
                _apply_definition(state, cls, parse_script(w[1].text, w[1].line), namespace, class_level=True)
            else:
                _apply_definition(state, cls, [Command(w[1:], cmd.line)], namespace, class_level=True)
        elif name in ("initialise", "initialize") and len(w) >= 2:
            for c in parse_script(w[1].text, w[1].line):
                if c.name == "variable":
                    for k in range(1, len(c.words), 2):
                        cls.attributes.append(Attribute(name=c.words[k].text, scope="class", visibility="protected",
                                                        default=c.arg(k + 1), lineno=c.line))
        elif name == "filter" and len(w) >= 2:
            cls.decorators.append("filter " + " ".join(x.text for x in w[1:]))


def _replace_method(cls: ClassInfo, m: Method) -> None:
    cls.methods = [x for x in cls.methods if not (x.name == m.name and x.is_classmethod == m.is_classmethod)]
    cls.methods.append(m)


# --------------------------------------------------------------------------- method bodies

class BodyFacts:
    def __init__(self, cls: ClassInfo, pm: PendingMethod, members: set[str], state: TclState):
        self.cls, self.m, self.pm, self.state = cls, pm.method, pm, state
        self.members = set(members)
        self.params = {p.name for p in self.m.params}
        self.loop_vars: dict[str, str] = {}
        self.local_classes: dict[str, str] = {}  # local var -> class name it was created from

    def run(self) -> None:
        cmds = parse_script(self.pm.body, self.pm.line)
        stmts = [c for c in cmds]
        self.m.is_stub = not stmts or all(self._is_error(c) or c.name == "return" and len(c.words) <= 2
                                          and not substitutions(c.words[-1]) for c in stmts)
        if stmts and all(self._is_error(c) for c in stmts):
            self.m.raises_not_implemented = True
            if self.m.kind == "method":
                self.m.is_abstract = bool(NOT_IMPLEMENTED.search(" ".join(w.text for c in stmts for w in c.words)))
        self.script(cmds)
        for var, src in self.loop_vars.items():
            if var in self.m.name_calls:
                self.m.attr_calls.setdefault(src, [])
                for call in self.m.name_calls[var]:
                    _add(self.m.attr_calls[src], call)

    @staticmethod
    def _is_error(c: Command) -> bool:
        return c.name in ("error", "throw") or (c.name == "return" and len(c.words) > 2 and c.arg(1) == "-code"
                                               and c.arg(2) == "error")

    def var_of(self, text: str) -> str | None:
        """``$name`` / ``${name}`` -> ``name``."""
        m = re.fullmatch(r"\$\{?([\w:]+)\}?", text.strip())
        return m.group(1) if m else None

    def script(self, cmds: list[Command]) -> None:
        for c in cmds:
            self.command(c)

    def nested(self, word: Word) -> None:
        self.script(parse_script(word.text, word.line))

    def created_class(self, text: str) -> str | None:
        cmd = _single_command(text)
        if cmd is None or len(cmd.words) < 2:
            return None
        if cmd.arg(1) in ("new", "create") and not cmd.name.startswith(("$", "[")):
            return cmd.name if cmd.name not in ("my", "self") else self.cls.name
        return None

    def command(self, c: Command) -> None:
        m, w = self.m, c.words
        # expressions are evaluated even when braced: follow their command substitutions too
        evaluated = c.name == "expr" or (c.name == "while" and len(w) >= 2)
        for k, word in enumerate(w):
            if word.kind == "brace" and evaluated and (c.name == "expr" or k == 1):
                word = Word(word.text, "bare", word.line)
            for sub in substitutions(word):
                self.script(parse_script(sub, word.line))
        name = c.name
        if name in ("my", "[self]") and len(w) >= 2:
            if w[1].text == "variable":
                for v in w[2:]:
                    self.members.add(v.text)
                    if m.is_classmethod:
                        _add(m.class_attr_refs, v.text)
            elif w[1].text not in ("new", "create"):
                _add(m.self_calls, w[1].text)
            else:
                _add(m.calls, self.cls.name)
        elif name == "variable" and len(w) >= 2:
            for v in w[1:]:
                self.members.add(v.text)
                if m.is_classmethod:
                    _add(m.class_attr_refs, v.text)
        elif name == "set" and len(w) >= 2:
            var = w[1].text
            value = w[2] if len(w) >= 3 else None
            if var in self.members:
                _add(m.attr_writes, var)
                if m.is_classmethod:
                    _add(m.class_attr_refs, var)
                if value is not None:
                    self.assign(var, value)
            elif value is not None:
                cls_name = self.created_class(value.text) if value.kind != "brace" else None
                if cls_name:
                    self.local_classes[var] = cls_name
        elif name in LIST_OPS and len(w) >= 2 and w[1].text in self.members:
            m.attr_calls.setdefault(w[1].text, [])
            _add(m.attr_calls[w[1].text], LIST_OPS[name])
            _add(m.attr_writes, w[1].text)
            self.member_attr(w[1].text, default_type="list")
        elif name == "dict" and len(w) >= 3:
            op, target = w[1].text, w[2].text
            if op in ("set", "lappend", "unset", "append", "incr", "update") and target in self.members:
                _add(m.attr_writes, target)
                m.attr_calls.setdefault(target, [])
                _add(m.attr_calls[target], f"dict {op}")
                self.member_attr(target, default_type="dict")
            elif op in ("for", "map") and len(w) >= 5:
                src = self.var_of(w[3].text)
                if src in self.members:
                    _add(m.iterated_attrs, src)
                    for v in parse_list(w[2].text):
                        self.loop_vars[v] = src
                self.nested(w[4])
            elif op in ("get", "exists", "keys", "values", "size") and (v := self.var_of(target)) in self.members:
                m.attr_calls.setdefault(v, [])
                _add(m.attr_calls[v], f"dict {op}")
                self.member_attr(v, default_type="dict")
            elif op == "with" and len(w) >= 4:
                self.nested(w[-1])
        elif name in ("foreach", "lmap") and len(w) >= 4:
            for k in range(1, len(w) - 1, 2):
                src = self.var_of(w[k + 1].text)
                if src in self.members:
                    _add(m.iterated_attrs, src)
                    for v in parse_list(w[k].text):
                        self.loop_vars[v] = src
            self.nested(w[-1])
        elif name == "return" and len(w) >= 2:
            last = w[-1].text.strip()
            if last in ("[self]", "[my self]") and w[-1].kind != "brace":
                m.returns_self = True
        elif name in ("if",):
            self.if_command(w)
        elif name in ("while",) and len(w) >= 3:
            self.nested(w[2])
        elif name == "for" and len(w) >= 5:
            for x in (w[1], w[3], w[4]):
                self.nested(x)
        elif name in ("catch", "eval", "time", "uplevel") and len(w) >= 2:
            body = w[-1] if name == "uplevel" else w[1]
            if body.kind == "brace":
                self.nested(body)
        elif name == "try" and len(w) >= 2:
            self.nested(w[1])  # handler bodies: the last word of each on/trap clause, and the finally script
            for k in range(2, len(w)):
                if w[k].kind == "brace" and (k == len(w) - 1 or w[k + 1].text in ("on", "trap", "finally")):
                    self.nested(w[k])
        elif name == "switch" and len(w) >= 3:
            last = w[-1]
            if last.kind == "brace" and len(parse_list(last.text)) % 2 == 0:
                for i, item in enumerate(parse_list(last.text)):
                    if i % 2 == 1 and item.strip() != "-":
                        self.script(parse_script(item, last.line))
            else:
                for k in range(len(w) - 1, 1, -2):
                    if w[k].kind == "brace":
                        self.nested(w[k])
        elif name == "oo::copy":
            _add(m.calls, "oo::copy")
        elif name == "next":
            pass
        elif name.startswith("$") or c.words[0].expand:
            var = self.var_of(name)
            method = w[1].text if len(w) >= 2 and not c.words[0].expand else "__call__"
            if var is None:
                return
            if method in ("new", "create"):
                m.dynamic_instantiation = True
            elif var in self.members:
                m.attr_calls.setdefault(var, [])
                _add(m.attr_calls[var], method)
            else:
                m.name_calls.setdefault(var, [])
                _add(m.name_calls[var], method)
        elif name.startswith("[") and len(w) >= 2 and w[1].text in ("new", "create"):
            m.dynamic_instantiation = True
        elif name == "error" or name == "throw":
            if NOT_IMPLEMENTED.search(" ".join(x.text for x in w[1:])):
                m.raises_not_implemented = True
        if len(w) >= 2 and w[1].text in ("new", "create") and not name.startswith(("$", "[")) and name not in ("my", "self"):
            _add(m.calls, name)

    def if_command(self, w: list[Word]) -> None:
        k = 1
        while k < len(w):
            # condition
            for sub in substitutions(Word(w[k].text, "bare", w[k].line)):
                self.script(parse_script(sub, w[k].line))
            self.isa_hint(w[k].text)
            k += 1
            if k < len(w) and w[k].text == "then":
                k += 1
            if k < len(w):
                self.nested(w[k])
                k += 1
            if k < len(w) and w[k].text == "elseif":
                k += 1
                continue
            if k < len(w) and w[k].text == "else":
                if k + 1 < len(w):
                    self.nested(w[k + 1])
                break
            break

    def isa_hint(self, text: str) -> None:
        for var, cls_name in re.findall(r"info\s+object\s+isa\s+typeof\s+\$\{?(\w+)\}?\s+([\w:]+)", text):
            self.local_classes[var] = cls_name
            self.m.ref_names.append(TypeRef(cls_name))

    def member_attr(self, name: str, default_type: str | None = None) -> Attribute | None:
        attr = self.cls.attribute(name)
        if attr is None and name in self.members and not self.m.is_classmethod:
            attr = Attribute(name=name, visibility="protected", lineno=self.pm.line)
            self.cls.attributes.append(attr)
        if attr is not None and default_type and attr.type is None:
            attr.type = default_type
        return attr

    def assign(self, var: str, value: Word) -> None:
        attr = self.member_attr(var)
        if attr is None:
            return
        text = value.text.strip()
        created = self.created_class(text) if value.kind != "brace" else None
        source_var = self.var_of(text) if value.kind != "brace" else None
        if created:
            if attr.origin != "injected":
                attr.origin = "created"
            if not attr.refs:
                attr.refs = [TypeRef(created)]
                attr.type = created
        elif source_var and source_var in self.params:
            self.state.from_params.add((self.cls.id, var))
            if self.m.kind == "constructor" or attr.origin in ("unknown", "literal"):
                attr.origin = "injected"
            hint = self.local_classes.get(source_var)
            if hint and not attr.refs:
                attr.refs, attr.type = [TypeRef(hint)], hint
        elif source_var and source_var in self.local_classes and not attr.refs:
            attr.refs, attr.type = [TypeRef(self.local_classes[source_var])], self.local_classes[source_var]
            if attr.origin == "unknown":
                attr.origin = "created"
        elif value.kind == "brace" and text == "" or text in ("[list]", "[dict create]", '""'):
            attr.type = attr.type or ("dict" if "dict" in text else "list" if text != '""' else "string")
            if attr.origin == "unknown":
                attr.origin = "literal"
            if attr.default is None and self.m.kind == "constructor":
                attr.default = text or "{}"
        elif re.fullmatch(r"-?\d+(\.\d+)?", text):
            attr.type = attr.type or ("double" if "." in text else "int")
            attr.origin = "literal" if attr.origin == "unknown" else attr.origin
            if self.m.kind == "constructor":
                attr.default = text


def _add(lst: list[str], value: str) -> None:
    if value not in lst:
        lst.append(value)


def _norm(name: str) -> str:
    return re.sub(r"[_\W\d]+", "", name).lower()


# --------------------------------------------------------------------------- entry point

def analyze_tcl(root: Path, project: Project, exclude: Iterable[str] = ()) -> None:
    state = TclState()
    for f in source_files(root, "tcl", exclude):
        module = add_path_module(project, root, f, "tcl")
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            project.warnings.append(f"{module.file}: cannot read ({exc})")
            continue
        _scan_file(state, parse_script(text), module, "", text.splitlines())

    # create classes
    qualified: dict[str, str] = {}
    for d in state.defs:
        if d.name in state.classes:
            continue
        short = d.name.rsplit("::", 1)[-1]
        ns = d.name.rpartition("::")[0]
        cid = f"{d.module.name}::{d.name}"
        cls = ClassInfo(id=cid, name=short, qualname=short, module=d.module.name, file=d.module.file, lineno=d.line,
                        language="tcl", namespace=ns or None, docstring=d.doc)
        if CLASS_CREATORS.get(d.creator):
            cls.stereotypes.append(CLASS_CREATORS[d.creator])
        elif d.creator.startswith("dialect:"):
            cls.decorators.append(f"defined with {d.creator.split(':', 1)[1]}")
        elif d.creator not in CLASS_CREATORS:
            cls.metaclass = d.creator
        state.classes[d.name] = cls
        qualified[d.name] = cid
        project.classes[cid] = cls
        d.module.classes.append(cid)
    for definition in state.definitions:
        cls = state.classes.get(definition.cls)
        if cls is None:
            if not definition.cls.startswith("oo::"):  # extending TclOO's own classes is legitimate
                project.warnings.append(f"{definition.module.file}: oo::define of unknown class {definition.cls}")
            continue
        _apply_definition(state, cls, definition.commands, definition.namespace)

    resolver = QualifiedResolver(qualified)
    scopes_of = {cls.id: _scopes(cls.namespace) for cls in state.classes.values()}
    for q, cls in state.classes.items():
        cls.base_ids = [resolver.resolve(b, scopes_of[cls.id]) for b in cls.bases]
        if cls.metaclass:
            cls.metaclass_id = resolver.resolve(cls.metaclass, scopes_of[cls.id])
        if q in state.mixins:
            cls.stereotypes.append("mixin")

    # bodies (members include inherited variables)
    by_id = {cls.id: cls for cls in state.classes.values()}

    def lineage(cid: str) -> list[ClassInfo]:
        out, stack = [], [cid]
        while stack:
            c = stack.pop()
            if c in by_id and by_id[c] not in out:
                out.append(by_id[c])
                stack.extend(filter(None, by_id[c].base_ids))
        return out

    for cls in state.classes.values():
        members = {a.name for c in lineage(cls.id) for a in c.attributes if a.scope == "instance"}
        for pm in state.bodies.get(cls.id, []):
            BodyFacts(cls, pm, members, state).run()
        if any(m.is_abstract for m in cls.methods) and "abstract" not in cls.stereotypes:
            cls.stereotypes.append("abstract")
        cls.is_abstract = "abstract" in cls.stereotypes

    # resolve references, then infer untyped collaborators from names and usage
    for cls in state.classes.values():
        scopes = scopes_of[cls.id]
        for m in cls.methods:
            for call in m.calls:
                target = resolver.resolve(call, scopes)
                if target:
                    m.call_targets[call] = target
            for ref in m.ref_names:
                ref.target = resolver.resolve(ref.name, scopes)
        for a in cls.attributes:
            for ref in a.refs:
                ref.target = resolver.resolve(ref.name, scopes)
    _infer_types(state, by_id, lineage)


def _scopes(namespace: str | None) -> list[str]:
    parts = namespace.split("::") if namespace else []
    return ["::".join(parts[:i]) for i in range(len(parts), 0, -1)]


def _infer_types(state: TclState, by_id: dict[str, ClassInfo], lineage) -> None:
    names = {_norm(c.name): c.id for c in by_id.values()}
    methods_of = {cid: {m.name for c in lineage(cid) for m in c.methods} for cid in by_id}
    roots_cache: dict[frozenset[str], str | None] = {}

    def family_root(candidates: set[str]) -> str | None:
        key = frozenset(candidates)
        if key not in roots_cache:
            roots = [c for c in candidates if not any(b in candidates for b in _all_bases(c, by_id))]
            roots_cache[key] = roots[0] if len(roots) == 1 else None
        return roots_cache[key]

    def widest(target: str, calls: set[str]) -> str:
        """Most general ancestor of ``target`` that still defines every method called on the variable."""
        best = target
        for base in _all_bases(target, by_id):
            if calls <= methods_of[base] and base in _all_bases(best, by_id):
                best = base
        return best

    for cls in by_id.values():
        for a in cls.attributes:
            calls_all = {c for m in cls.methods for c in m.attr_calls.get(a.name, [])
                         if not c.startswith(("dict ", "lappend", "insert", "remove", "lset", "__"))}
            # created as one class but reassigned from parameters: the variable holds the whole family
            if a.refs and a.refs[0].target and (cls.id, a.name) in state.from_params and calls_all:
                wide = widest(a.refs[0].target, calls_all)
                if wide != a.refs[0].target:
                    a.refs = [TypeRef(by_id[wide].name, a.refs[0].multiplicity, wide)]
                    a.type = by_id[wide].name
            if a.refs or a.kind != "field":
                continue
            calls = {c for m in cls.methods for c in m.attr_calls.get(a.name, [])
                     if not c.startswith(("dict ", "lappend", "insert", "remove", "lset", "__"))}
            many = a.type in ("list", "dict") or any(c in ("lappend", "insert") for m in cls.methods
                                                     for c in m.attr_calls.get(a.name, []))
            # 1. a class named like the variable (sortStrategy -> SortStrategy, observers -> Observer)
            hint = _norm(a.name[:-1] if many and a.name.endswith("s") else a.name)
            target = names.get(hint)
            # 2. the single class family defining every method called on it
            if target is None and calls:
                candidates = {cid for cid, ms in methods_of.items() if calls <= ms}
                target = family_root(candidates) if candidates else None
            # 3. classes whose name ends with the variable name (strategy -> SortStrategy family)
            if target is None and len(hint) >= 5:
                candidates = {cid for key, cid in names.items() if key.endswith(hint) and cid != cls.id}
                target = family_root(candidates) if candidates else None
            if target is not None:
                tcls = by_id[target]
                a.refs = [TypeRef(tcls.name, "*" if many else "1", target)]
                a.type = f"{'list of ' if many else ''}{tcls.name}"
                if a.origin == "unknown":
                    a.origin = "injected" if many else "annotated"


def _all_bases(cid: str, by_id: dict[str, ClassInfo]) -> set[str]:
    out, stack = set(), list(filter(None, by_id[cid].base_ids))
    while stack:
        c = stack.pop()
        if c not in out and c in by_id:
            out.add(c)
            stack.extend(filter(None, by_id[c].base_ids))
    return out
