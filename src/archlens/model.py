"""Data model produced by the analyzer and consumed by the pattern detectors and renderer."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Param:
    name: str
    annotation: str | None = None
    default: str | None = None
    kind: str = "positional"  # positional | vararg | kwonly | kwarg


@dataclass
class TypeRef:
    """A reference to a class name found inside a type expression or value."""

    name: str
    multiplicity: str = "1"  # "1", "0..1" or "*"
    target: str | None = None  # resolved class id, filled in by the resolver


@dataclass
class Attribute:
    name: str
    type: str | None = None
    default: str | None = None
    scope: str = "instance"  # instance | class
    kind: str = "field"  # field | property | enum_member
    visibility: str = "public"  # public | protected | private
    origin: str = "unknown"  # created | injected | annotated | literal | unknown
    readonly: bool = False
    lineno: int | None = None
    refs: list[TypeRef] = field(default_factory=list)


@dataclass
class Method:
    name: str
    params: list[Param] = field(default_factory=list)
    returns: str | None = None
    decorators: list[str] = field(default_factory=list)
    visibility: str = "public"
    is_abstract: bool = False
    is_static: bool = False
    is_classmethod: bool = False
    is_async: bool = False
    is_stub: bool = False
    is_generator: bool = False
    lineno: int | None = None
    docstring: str | None = None
    # Behavioural facts used by the pattern detectors.
    returns_self: bool = False
    self_calls: list[str] = field(default_factory=list)
    attr_calls: dict[str, list[str]] = field(default_factory=dict)
    name_calls: dict[str, list[str]] = field(default_factory=dict)
    iterated_attrs: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    class_attr_refs: list[str] = field(default_factory=list)
    attr_writes: list[str] = field(default_factory=list)
    raises_not_implemented: bool = False
    dynamic_instantiation: bool = False  # calls a class looked up at run time, e.g. ``cls = lookup(name); cls()``
    ref_names: list[TypeRef] = field(default_factory=list)  # signature type refs

    @property
    def signature(self) -> str:
        parts = []
        for p in self.params:
            prefix = {"vararg": "*", "kwarg": "**"}.get(p.kind, "")
            text = prefix + p.name
            if p.annotation:
                text += f": {p.annotation}"
            parts.append(text)
        sig = f"{self.name}({', '.join(parts)})"
        if self.returns:
            sig += f" -> {self.returns}"
        return sig


@dataclass
class ClassInfo:
    id: str
    name: str
    qualname: str
    module: str
    file: str
    lineno: int
    end_lineno: int | None = None
    docstring: str | None = None
    bases: list[str] = field(default_factory=list)
    base_ids: list[str | None] = field(default_factory=list)
    base_args: list[TypeRef] = field(default_factory=list)  # type arguments of generic bases, e.g. Factory[Product]
    metaclass_id: str | None = None
    metaclass: str | None = None
    decorators: list[str] = field(default_factory=list)
    attributes: list[Attribute] = field(default_factory=list)
    methods: list[Method] = field(default_factory=list)
    stereotypes: list[str] = field(default_factory=list)
    is_abstract: bool = False
    subclasses: list[str] = field(default_factory=list)
    patterns: list[dict[str, Any]] = field(default_factory=list)

    def method(self, name: str) -> Method | None:
        for m in self.methods:
            if m.name == name:
                return m
        return None

    def attribute(self, name: str) -> Attribute | None:
        for a in self.attributes:
            if a.name == name:
                return a
        return None

    @property
    def is_data(self) -> bool:
        return any(s in self.stereotypes for s in ("dataclass", "namedtuple", "typeddict", "model", "attrs"))


@dataclass
class Relation:
    source: str
    target: str
    kind: str  # inheritance | realization | composition | aggregation | dependency
    label: str | None = None
    multiplicity: str | None = None


@dataclass
class PatternMatch:
    key: str
    participants: dict[str, str]  # class id -> role
    evidence: list[str] = field(default_factory=list)
    confidence: float = 0.5


@dataclass
class ModuleInfo:
    name: str
    file: str
    is_package: bool = False
    docstring: str | None = None
    classes: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    imports: dict[str, str] = field(default_factory=dict)


@dataclass
class Project:
    name: str
    root: str
    modules: dict[str, ModuleInfo] = field(default_factory=dict)
    classes: dict[str, ClassInfo] = field(default_factory=dict)
    relations: list[Relation] = field(default_factory=list)
    patterns: list[PatternMatch] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
