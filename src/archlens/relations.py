"""Language-independent relation building.

Front-ends parse their language and *resolve* names (bases, attribute types, signature types and
instantiated classes) to class ids. This module turns those resolved references into UML relations
and propagates inherited stereotypes, identically for every language.
"""

from __future__ import annotations

from .model import Project, Relation

STRENGTH = {"composition": 3, "aggregation": 2, "dependency": 1}
INHERITED_STEREOTYPES = ("exception", "model", "metaclass", "enum", "typeddict")


def derive_relations(project: Project) -> None:
    rels: dict[tuple[str, str, str], Relation] = {}
    assoc: dict[tuple[str, str], Relation] = {}

    def add_assoc(src: str, dst: str, kind: str, label: str | None, mult: str | None) -> None:
        cur = assoc.get((src, dst))
        if cur is None or STRENGTH[kind] > STRENGTH[cur.kind]:
            assoc[(src, dst)] = Relation(src, dst, kind, label, mult)
        elif cur.kind == kind and label and kind != "dependency":
            if label not in (cur.label or "").split(", "):
                cur.label = ", ".join(filter(None, [cur.label, label]))
            if mult == "*" or cur.multiplicity is None:
                cur.multiplicity = mult

    for cls in project.classes.values():
        cls.subclasses = []
    for cls in project.classes.values():
        for target in cls.base_ids:
            if target and target != cls.id and target in project.classes:
                tgt = project.classes[target]
                kind = "realization" if "protocol" in tgt.stereotypes else "inheritance"
                rels[(cls.id, target, kind)] = Relation(cls.id, target, kind)
                if cls.id not in tgt.subclasses:
                    tgt.subclasses.append(cls.id)
        if cls.metaclass and cls.metaclass_id:
            add_assoc(cls.id, cls.metaclass_id, "dependency", "«metaclass»", None)
        for attr in cls.attributes:
            if attr.kind == "enum_member":
                continue
            for ref in attr.refs:
                if not ref.target:
                    continue
                if attr.kind == "property" or attr.origin == "classref":
                    kind = "dependency"
                elif attr.ownership == "owned":
                    kind = "composition"
                elif attr.ownership in ("shared", "reference"):
                    kind = "aggregation"
                elif attr.origin == "created" or (attr.origin != "injected" and cls.is_data):
                    kind = "composition"
                else:
                    kind = "aggregation"
                add_assoc(cls.id, ref.target, kind, attr.name, ref.multiplicity)
        for m in cls.methods:
            for ref in m.ref_names:
                if ref.target and ref.target != cls.id:
                    add_assoc(cls.id, ref.target, "dependency", None, None)
            for target in m.call_targets.values():
                if target and target != cls.id:
                    add_assoc(cls.id, target, "dependency", None, None)

    inherit_pairs = {(s, t) for (s, t, _k) in rels}
    project.relations = list(rels.values())
    for (s, t), r in assoc.items():
        if r.kind == "dependency" and ((s, t) in inherit_pairs or (t, s) in inherit_pairs):
            continue
        project.relations.append(r)

    # Stereotypes that are inherited: subclasses of exceptions, pydantic models, metaclasses, enums and
    # TypedDicts keep the nature of their base. A metaclass applies to every subclass as well.
    changed = True
    while changed:
        changed = False
        for cls in project.classes.values():
            for b in filter(None, cls.base_ids):
                base = project.classes.get(b)
                if base is None:
                    continue
                for st in INHERITED_STEREOTYPES:
                    if st in base.stereotypes and st not in cls.stereotypes:
                        cls.stereotypes.append(st)
                        changed = True
                if cls.metaclass_id is None and base.metaclass_id is not None:
                    cls.metaclass_id = base.metaclass_id
                    changed = True


class QualifiedResolver:
    """Name lookup for languages with ``::``-separated namespaces (C++, Tcl).

    Classes are indexed by their fully qualified name; a reference is resolved from the innermost
    enclosing scope outwards, then by unique suffix, like the languages' own lookup rules.
    """

    def __init__(self, qualified: dict[str, str], aliases: dict[str, str] | None = None):
        self.qualified = qualified  # "ns::Outer::Inner" -> class id
        self.aliases = aliases or {}
        self.by_short: dict[str, list[str]] = {}
        for q, cid in qualified.items():
            self.by_short.setdefault(q.rsplit("::", 1)[-1], []).append(cid)

    def resolve(self, name: str | None, scopes: list[str]) -> str | None:
        """``scopes`` lists enclosing scopes innermost first, e.g. ``["ns::Outer", "ns", ""]``."""
        if not name:
            return None
        name = name.strip()
        absolute = name.startswith("::")
        name = name.lstrip(":")
        for _ in range(5):  # follow alias chains
            target = self._lookup_alias(name, scopes)
            if target is None or target == name:
                break
            name = target.lstrip(":")
        if absolute:
            return self.qualified.get(name)
        for scope in [*scopes, ""]:
            hit = self.qualified.get(f"{scope}::{name}" if scope else name)
            if hit:
                return hit
        short = name.rsplit("::", 1)[-1]
        candidates = [c for q, c in self.qualified.items() if q == name or q.endswith("::" + name)]
        if len(candidates) == 1:
            return candidates[0]
        if "::" not in name and len(self.by_short.get(short, [])) == 1:
            return self.by_short[short][0]
        return None

    def _lookup_alias(self, name: str, scopes: list[str]) -> str | None:
        for scope in [*scopes, ""]:
            key = f"{scope}::{name}" if scope else name
            if key in self.aliases:
                return self.aliases[key]
        return None
