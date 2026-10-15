"""Heuristic detection of common design patterns from the static class model.

Each detector looks for the structural and behavioural signature of a pattern
(who inherits from whom, which attributes hold which types, which methods
delegate, iterate or return ``self``) and records a :class:`PatternMatch` with
the participating classes, their roles, human readable evidence and a
confidence score between 0 and 1.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable, Iterable

from .model import Attribute, ClassInfo, Method, PatternMatch, Project

# key: (display name, category, colour, short description)
CATALOG: dict[str, tuple[str, str, str, str]] = {
    "singleton": ("Singleton", "creational", "#dc2626", "Ensures a class has a single shared instance."),
    "factory": ("Factory", "creational", "#ea580c", "Creates objects without exposing the concrete class."),
    "abstract_factory": ("Abstract Factory", "creational", "#b45309", "Interface for creating families of related objects."),
    "builder": ("Builder", "creational", "#db2777", "Builds a complex object step by step with a fluent API."),
    "prototype": ("Prototype", "creational", "#be123c", "Creates new objects by cloning an existing instance."),
    "adapter": ("Adapter", "structural", "#0891b2", "Converts the interface of a class into another expected interface."),
    "decorator": ("Decorator", "structural", "#2563eb", "Wraps an object of the same interface to add behaviour."),
    "composite": ("Composite", "structural", "#4f46e5", "Composes objects into trees treated uniformly."),
    "proxy": ("Proxy", "structural", "#0d9488", "Surrogate controlling access to another object."),
    "facade": ("Facade", "structural", "#0369a1", "Simplified entry point to a set of collaborating classes."),
    "observer": ("Observer", "behavioral", "#16a34a", "Subscribers are notified when a subject changes."),
    "strategy": ("Strategy", "behavioral", "#7c3aed", "Interchangeable algorithms behind a common interface."),
    "state": ("State", "behavioral", "#c026d3", "Behaviour changes with internal state objects."),
    "template_method": ("Template Method", "behavioral", "#65a30d", "Algorithm skeleton with steps deferred to subclasses."),
    "command": ("Command", "behavioral", "#059669", "Encapsulates a request as an object."),
    "visitor": ("Visitor", "behavioral", "#7e22ce", "Operations on an object structure kept outside its classes."),
    "iterator": ("Iterator", "behavioral", "#4d7c0f", "Sequential access to elements of an aggregate."),
    "chain": ("Chain of Responsibility", "behavioral", "#4338ca", "Passes a request along a chain of handlers."),
    "registry": ("Registry", "idiom", "#a16207", "Central lookup table of registered classes or objects."),
    "context_manager": ("Context Manager", "idiom", "#78716c", "Resource acquisition/release via the with statement."),
    "data_class": ("Data Class", "idiom", "#64748b", "Plain data holder / value object."),
    "interface": ("Interface", "idiom", "#475569", "Abstract base class or protocol without implementation."),
}

CATEGORY_ORDER = {"creational": 0, "structural": 1, "behavioral": 2, "idiom": 3}

OBSERVER_ATTR = re.compile(r"(observer|listener|subscriber|callback|handler|watcher|hook|sink|receiver)s?", re.I)
ADD_METHOD = re.compile(r"^(attach|subscribe|register|add_(listener|observer|handler|callback|subscriber)|on|connect|add_hook|listen|watch)$")
NOTIFY_METHOD = re.compile(r"^_?(notify|emit|publish|fire|dispatch|trigger|broadcast|signal|send|notify_\w+|_notify\w*)$")
CREATE_METHOD = re.compile(r"^(create|make|new|build|get|produce|construct|spawn)(_\w+)?$")
BUILD_METHOD = {"build", "create", "get_result", "result", "construct", "done", "finish", "to_object", "make"}
COMMAND_METHODS = {"execute", "run", "__call__", "do", "undo", "perform", "apply", "invoke", "redo"}
CHAIN_ATTR = re.compile(r"(next|successor|_next|parent_handler|next_handler|_successor)", re.I)
REGISTRY_ATTR = re.compile(r"(registry|registered|plugins|_classes|_types|_handlers|_factories|catalog|_map|_lookup)", re.I)


class Context:
    def __init__(self, project: Project):
        self.p = project
        self.classes = project.classes
        self.children: dict[str, list[str]] = defaultdict(list)
        self.parents: dict[str, list[str]] = defaultdict(list)
        for r in project.relations:
            if r.kind in ("inheritance", "realization"):
                self.children[r.target].append(r.source)
                self.parents[r.source].append(r.target)
        self._anc: dict[str, set[str]] = {}

    def ancestors(self, cid: str) -> set[str]:
        if cid not in self._anc:
            out: set[str] = set()
            stack = list(self.parents.get(cid, []))
            while stack:
                c = stack.pop()
                if c not in out:
                    out.add(c)
                    stack.extend(self.parents.get(c, []))
            self._anc[cid] = out
        return self._anc[cid]

    def descendants(self, cid: str) -> set[str]:
        out: set[str] = set()
        stack = list(self.children.get(cid, []))
        while stack:
            c = stack.pop()
            if c not in out:
                out.add(c)
                stack.extend(self.children.get(c, []))
        return out

    def related(self, a: str, b: str) -> bool:
        return a == b or b in self.ancestors(a) or a in self.ancestors(b)

    def all_methods(self, cid: str) -> dict[str, Method]:
        """Methods of the class including inherited ones (own definitions win)."""
        result: dict[str, Method] = {}
        for c in [cid, *sorted(self.ancestors(cid))]:
            for m in self.classes[c].methods:
                result.setdefault(m.name, m)
        return result

    def is_abstractish(self, cid: str) -> bool:
        cls = self.classes[cid]
        return cls.is_abstract or any(m.is_stub and m.raises_not_implemented for m in cls.methods)

    @staticmethod
    def attr_targets(attr: Attribute) -> list[tuple[str, str]]:
        return [(r.target, r.multiplicity) for r in attr.refs if r.target]

    def name(self, cid: str) -> str:
        return self.classes[cid].name


def _public(methods: Iterable[Method]) -> list[Method]:
    return [m for m in methods if m.visibility == "public" and not m.name.startswith("__")]


# --------------------------------------------------------------------------- creational

def detect_singleton(ctx: Context) -> list[PatternMatch]:
    out = []
    for cid, cls in ctx.classes.items():
        ev = []
        new = cls.method("__new__")
        if new and any("instance" in a.lower() for a in new.class_attr_refs):
            ev.append("__new__ caches and returns a shared instance")
        for m in cls.methods:
            if (m.is_classmethod or m.is_static) and re.match(r"^(get_?instance|instance|shared|default|get|current)$", m.name, re.I) \
                    and any("instance" in a.lower() for a in m.class_attr_refs):
                ev.append(f"{m.name}() returns the cached class-level instance")
        if "metaclass" in cls.stereotypes:
            call = cls.method("__call__")
            if call and any("instance" in a.lower() for a in call.class_attr_refs):
                ev.append("metaclass __call__ caches instances per class")
        if cls.metaclass and "singleton" in cls.metaclass.lower():
            ev.append(f"uses metaclass {cls.metaclass}")
        if any("singleton" in d.lower() for d in cls.decorators):
            ev.append("decorated as singleton")
        if ev:
            role = "Singleton metaclass" if "metaclass" in cls.stereotypes else "Singleton"
            out.append(PatternMatch("singleton", {cid: role}, ev, 0.9 if len(ev) > 1 or "__new__" in ev[0] else 0.75))
    return out


def detect_factories(ctx: Context) -> list[PatternMatch]:
    out = []
    for cid, cls in ctx.classes.items():
        abstract_creators = [m for m in cls.methods if CREATE_METHOD.match(m.name) and m.is_abstract and m.name != "get"]
        if len(abstract_creators) >= 2:
            parts = {cid: "Abstract Factory"}
            for d in ctx.descendants(cid):
                parts[d] = "Concrete Factory"
            out.append(PatternMatch("abstract_factory", parts,
                                    [f"abstract creation methods: {', '.join(m.name + '()' for m in abstract_creators)}",
                                     f"{len(parts) - 1} concrete factories"],
                                    0.85 if len(parts) > 1 else 0.6))
            continue
        if abstract_creators and ctx.descendants(cid):
            m = abstract_creators[0]
            parts = {cid: "Creator"}
            for d in ctx.descendants(cid):
                parts[d] = "Concrete Creator"
            out.append(PatternMatch("factory", parts,
                                    [f"factory method {m.name}() deferred to subclasses (Factory Method)"], 0.8))
            continue
        ev = []
        parts: dict[str, str] = {cid: "Factory"}
        for m in cls.methods:
            if not (CREATE_METHOD.match(m.name) or m.name.startswith(("create_", "make_", "new_"))):
                continue
            created = set()
            for call in m.calls:
                t = _resolve_call(ctx, cls, call)
                if t and t != cid:
                    created.add(t)
            ret = next((r.target for r in m.ref_names if r.target), None)
            if len(created) >= 2:
                ev.append(f"{m.name}() instantiates {len(created)} different classes")
                for t in created:
                    parts.setdefault(t, "Product")
                if ret:
                    parts[ret] = "Product (abstract)"
            elif created and ret and ret not in created and any(ret in ctx.ancestors(t) for t in created):
                ev.append(f"{m.name}() returns a {ctx.name(ret)} subtype")
                for t in created:
                    parts.setdefault(t, "Product")
                parts[ret] = "Product (abstract)"
        if cls.name.endswith("Factory") and not ev and cls.methods:
            ev.append("name ends with 'Factory'")
            out.append(PatternMatch("factory", parts, ev, 0.55))
        elif ev:
            if cls.name.endswith("Factory"):
                ev.append("name ends with 'Factory'")
            out.append(PatternMatch("factory", parts, ev, 0.85 if len(ev) > 1 else 0.7))
    return out


def _resolve_call(ctx: Context, cls: ClassInfo, call: str) -> str | None:
    from .analyzer import Resolver  # local import to avoid a cycle

    resolver = getattr(ctx, "_resolver", None)
    if resolver is None:
        resolver = ctx._resolver = Resolver(ctx.p)  # type: ignore[attr-defined]
    head = call.rsplit(".", 1)[-1]
    if not head[:1].isupper():
        return None
    return resolver.resolve(call, cls.module, cls)


def detect_builder(ctx: Context) -> list[PatternMatch]:
    out = []
    for cid, cls in ctx.classes.items():
        fluent = [m for m in cls.methods if m.returns_self and not m.name.startswith("__")]
        builds = [m for m in cls.methods if m.name in BUILD_METHOD or m.name.startswith("build")]
        if len(fluent) >= 2 and builds:
            parts = {cid: "Builder"}
            for b in builds:
                for call in b.calls:
                    t = _resolve_call(ctx, cls, call)
                    if t and t != cid:
                        parts[t] = "Product"
                for r in b.ref_names:
                    if r.target and r.target != cid:
                        parts[r.target] = "Product"
            out.append(PatternMatch("builder", parts,
                                    [f"fluent methods returning self: {', '.join(m.name for m in fluent[:5])}",
                                     f"terminal method {builds[0].name}()"], 0.9))
        elif cls.name.endswith("Builder") and (fluent or builds):
            out.append(PatternMatch("builder", {cid: "Builder"}, ["name ends with 'Builder'"], 0.6))
    return out


def detect_prototype(ctx: Context) -> list[PatternMatch]:
    out = []
    for cid, cls in ctx.classes.items():
        for m in cls.methods:
            if m.name not in ("clone", "copy", "__copy__", "__deepcopy__", "duplicate"):
                continue
            uses_copy = any(c in ("copy.deepcopy", "copy.copy", "deepcopy", "copy") for c in m.calls)
            self_type = any(c in (cls.name, "type", "self.__class__", "cls") for c in m.calls)
            if uses_copy or self_type or m.name in ("__copy__", "__deepcopy__"):
                parts = {cid: "Prototype"}
                for d in ctx.descendants(cid):
                    parts[d] = "Concrete Prototype"
                out.append(PatternMatch("prototype", parts, [f"{m.name}() produces a copy of the instance"],
                                        0.85 if m.name == "clone" else 0.65))
                break
    return out


# --------------------------------------------------------------------------- structural

def _delegations(cls: ClassInfo, attr: str) -> dict[str, list[str]]:
    """Map method name -> methods called on ``self.<attr>`` inside it."""
    return {m.name: m.attr_calls[attr] for m in cls.methods if attr in m.attr_calls}


def detect_wrappers(ctx: Context) -> list[PatternMatch]:
    """Decorator, Proxy, Chain of Responsibility, Adapter and Composite share a 'wrapping' shape."""
    out = []
    for cid, cls in ctx.classes.items():
        anc = ctx.ancestors(cid)
        lineage = anc | {cid}
        done = False
        for attr in cls.attributes:
            if attr.kind != "field" or attr.scope != "instance":
                continue
            for target, mult in ctx.attr_targets(attr):
                deleg = _delegations(cls, attr.name)
                iterated = any(attr.name in m.iterated_attrs for m in cls.methods)
                # Composite: holds many of its own component type
                if mult == "*" and target in lineage:
                    if iterated or deleg or any(m.name.startswith(("add", "remove", "append")) for m in cls.methods):
                        component = target
                        parts = {cid: "Composite", component: "Component"} if component != cid else {cid: "Composite"}
                        for leaf in ctx.descendants(component):
                            parts.setdefault(leaf, "Leaf")
                        ev = [f"'{attr.name}' holds many {ctx.name(component)} objects"]
                        if iterated:
                            ev.append(f"operations iterate over '{attr.name}'")
                        out.append(PatternMatch("composite", parts, ev, 0.9 if component != cid else 0.7))
                        done = True
                        break
                if mult == "*":
                    continue
                same_name = [m for m, calls in deleg.items() if m in calls]
                if target in lineage and (CHAIN_ATTR.search(attr.name) or cls.method("set_next")):
                    parts = {cid: "Handler"}
                    if target != cid:
                        parts[target] = "Handler (abstract)"
                    for d in ctx.descendants(target):
                        parts.setdefault(d, "Concrete Handler")
                    out.append(PatternMatch("chain", parts,
                                            [f"'{attr.name}' links to the next {ctx.name(target)}",
                                             *([f"{same_name[0]}() forwards the request"] if same_name else [])],
                                            0.85 if same_name else 0.65))
                    done = True
                    break
                if target in lineage and target != cid:
                    is_proxy = "proxy" in cls.name.lower() or attr.origin == "created" \
                        or any(attr.name in m.attr_writes for m in cls.methods if m.name != "__init__")
                    if same_name or deleg or is_proxy:
                        key = "proxy" if is_proxy else "decorator"
                        role = "Proxy" if is_proxy else "Decorator"
                        parts = {cid: role, target: "Subject" if is_proxy else "Component"}
                        if not is_proxy:
                            for sib in ctx.descendants(target):
                                if sib != cid and sib not in ctx.ancestors(cid):
                                    parts.setdefault(sib, "Concrete Decorator" if sib in ctx.descendants(cid)
                                                     else "Concrete Component")
                        ev = [f"is a {ctx.name(target)} and wraps a {ctx.name(target)} in '{attr.name}'"]
                        if same_name:
                            ev.append(f"forwards {', '.join(m + '()' for m in same_name[:4])} to the wrapped object")
                        out.append(PatternMatch(key, parts, ev, 0.9 if same_name else 0.7))
                        done = True
                        break
                elif target != cid and (shared_ifaces := sorted(a for a in anc & ctx.ancestors(target)
                                                                 if ctx.is_abstractish(a))) and (
                        "proxy" in cls.name.lower() or same_name
                        or any(attr.name in m.attr_writes for m in cls.methods if m.name != "__init__")):
                    # Proxy: same (abstract) interface as the real subject it creates or controls access to
                    shared = shared_ifaces[0]
                    lazy = any(attr.name in m.attr_writes for m in cls.methods if m.name != "__init__")
                    ev = [f"implements {ctx.name(shared)} like the real subject {ctx.name(target)} held in '{attr.name}'"]
                    if lazy:
                        ev.append("creates the real subject lazily on first use")
                    out.append(PatternMatch("proxy", {cid: "Proxy", target: "Real Subject", shared: "Subject"}, ev,
                                            0.85 if lazy or "proxy" in cls.name.lower() else 0.65))
                    done = True
                    break
                elif target not in lineage and not ctx.related(cid, target) and deleg and anc:
                    # Adapter: implements an abstract target and translates calls to an unrelated adaptee
                    overridden = [m.name for m in _public(cls.methods)
                                  if any(a.method(m.name) for a in map(ctx.classes.get, anc) if a)]
                    translated = [m for m in overridden if m in deleg and m not in deleg[m]]
                    if translated and (len(translated) * 2 >= len(overridden) or "adapter" in cls.name.lower()):
                        tgt = next((a for a in ctx.parents[cid]), None)
                        parts = {cid: "Adapter", target: "Adaptee"}
                        if tgt:
                            parts[tgt] = "Target"
                        out.append(PatternMatch("adapter", parts,
                                                [f"implements {ctx.name(tgt) if tgt else 'its base'} by translating calls to "
                                                 f"{ctx.name(target)} ('{attr.name}')",
                                                 f"translated methods: {', '.join(translated[:4])}"],
                                                0.85 if "adapter" in cls.name.lower() else 0.7))
                        done = True
                        break
            if done:
                break
        if done:
            continue
        # name based fallbacks and dynamic proxies
        ga = cls.method("__getattr__")
        if ga and ga.attr_calls:
            wrapped = next(iter(ga.attr_calls))
            out.append(PatternMatch("proxy", {cid: "Proxy"}, [f"__getattr__ forwards attribute access to '{wrapped}'"], 0.75))
        elif "adapter" in cls.name.lower() and any(_delegations(cls, a.name) for a in cls.attributes):
            out.append(PatternMatch("adapter", {cid: "Adapter"}, ["name contains 'Adapter' and delegates to a wrapped object"], 0.6))
        elif cls.name.lower().endswith("proxy") and cls.attributes:
            out.append(PatternMatch("proxy", {cid: "Proxy"}, ["name ends with 'Proxy'"], 0.5))
    return out


def detect_facade(ctx: Context) -> list[PatternMatch]:
    out = []
    for cid, cls in ctx.classes.items():
        collaborators: dict[str, str] = {}
        for attr in cls.attributes:
            if attr.kind != "field":
                continue
            for target, _mult in ctx.attr_targets(attr):
                tc = ctx.classes[target]
                if ctx.related(cid, target) or tc.is_data or "enum" in tc.stereotypes or "exception" in tc.stereotypes:
                    continue
                collaborators.setdefault(attr.name, target)
        if len(set(collaborators.values())) < 3:
            continue
        orchestrating = [m for m in _public(cls.methods)
                         if len([a for a in m.attr_calls if a in collaborators]) >= 2]
        named = "facade" in cls.name.lower()
        if orchestrating or named:
            parts = {cid: "Facade"}
            for t in collaborators.values():
                parts.setdefault(t, "Subsystem")
            ev = [f"coordinates {len(set(collaborators.values()))} subsystem classes"]
            if orchestrating:
                ev.append(f"{', '.join(m.name + '()' for m in orchestrating[:3])} orchestrate several collaborators")
            out.append(PatternMatch("facade", parts, ev, 0.8 if named or len(orchestrating) >= 2 else 0.6))
    return out


# --------------------------------------------------------------------------- behavioural

def detect_observer(ctx: Context) -> list[PatternMatch]:
    out = []
    for cid, cls in ctx.classes.items():
        for attr in cls.attributes:
            if attr.kind != "field":
                continue
            collection = any(m == "*" for _, m in ctx.attr_targets(attr)) or \
                (attr.type or "").split("[")[0].lower() in ("list", "set", "dict", "weakset", "defaultdict", "deque") \
                or any(t in (attr.type or "") for t in ("List[", "Set[", "list[", "set[", "dict[", "Dict["))
            if not collection:
                continue
            notifies = [m for m in cls.methods if attr.name in m.iterated_attrs and attr.name in m.attr_calls]
            adds = [m for m in cls.methods if attr.name in m.attr_calls and
                    any(c in ("append", "add", "setdefault", "insert", "extend") for c in m.attr_calls[attr.name])
                    and m.name != "__init__"]
            named = bool(OBSERVER_ATTR.search(attr.name))
            if not notifies and not (named and adds):
                continue
            if not (named or any(ADD_METHOD.match(m.name) for m in adds) or any(NOTIFY_METHOD.match(m.name) for m in notifies)):
                continue
            parts = {cid: "Subject"}
            for target, _ in ctx.attr_targets(attr):
                parts.setdefault(target, "Observer")
                for d in ctx.descendants(target):
                    parts.setdefault(d, "Concrete Observer")
            ev = [f"keeps subscribers in '{attr.name}'"]
            if adds:
                ev.append(f"{adds[0].name}() registers subscribers")
            if notifies:
                ev.append(f"{notifies[0].name}() iterates subscribers and calls them")
            out.append(PatternMatch("observer", parts, ev, 0.9 if adds and notifies else 0.65))
            break
    return out


def detect_strategy_state(ctx: Context) -> list[PatternMatch]:
    out = []
    for cid, cls in ctx.classes.items():
        for attr in cls.attributes:
            if attr.kind != "field" or attr.scope != "instance":
                continue
            for target, mult in ctx.attr_targets(attr):
                if mult == "*" or ctx.related(cid, target):
                    continue
                impls = ctx.descendants(target)
                tcls = ctx.classes[target]
                if tcls.is_data or "enum" in tcls.stereotypes:
                    continue
                if not ctx.is_abstractish(target) and (len(impls) < 2 or attr.origin != "injected"):
                    continue  # a concrete collaborator only counts when its variant is injected
                if not impls and "protocol" not in tcls.stereotypes:
                    continue
                deleg = _delegations(cls, attr.name)
                iface = set(ctx.all_methods(target))
                used = sorted({c for calls in deleg.values() for c in calls if c in iface})
                if not used:
                    continue
                is_state = "state" in attr.name.lower() or tcls.name.lower().endswith("state")
                key = "state" if is_state else "strategy"
                role = "State" if is_state else "Strategy"
                parts = {cid: "Context", target: role}
                for d in impls:
                    parts.setdefault(d, f"Concrete {role}")
                ev = [f"'{attr.name}' holds an interchangeable {tcls.name} ({len(impls)} implementations)",
                      f"delegates via {', '.join(u + '()' for u in used[:3])}"]
                if is_state and any(attr.name in m.attr_writes for m in cls.methods if m.name != "__init__"):
                    ev.append(f"transitions by reassigning '{attr.name}'")
                out.append(PatternMatch(key, parts, ev, 0.85 if len(impls) >= 2 else 0.65))
    return out


def detect_template_method(ctx: Context) -> list[PatternMatch]:
    out = []
    for cid, cls in ctx.classes.items():
        subs = ctx.descendants(cid)
        if not subs:
            continue
        hooks = {m.name for m in cls.methods if m.is_abstract or (m.is_stub and m.raises_not_implemented)}
        if not hooks:
            continue
        for m in cls.methods:
            if m.is_abstract or m.is_stub:
                continue
            steps = [s for s in m.self_calls if s in hooks]
            if steps:
                parts = {cid: "Abstract Class"}
                for s in subs:
                    if any(ctx.classes[s].method(h) for h in steps):
                        parts[s] = "Concrete Class"
                out.append(PatternMatch("template_method", parts,
                                        [f"{m.name}() defines the algorithm and calls abstract steps "
                                         f"{', '.join(x + '()' for x in steps[:4])}"],
                                        0.9 if len(steps) >= 2 else 0.75))
                break
    return out


def detect_command(ctx: Context) -> list[PatternMatch]:
    out = []
    bases_done: set[str] = set()
    for cid, cls in ctx.classes.items():
        abstract_cmds = [m for m in cls.methods if m.name in COMMAND_METHODS and (m.is_abstract or m.is_stub)]
        impls = [d for d in ctx.descendants(cid)
                 if any(ctx.classes[d].method(m.name) for m in abstract_cmds)]
        if abstract_cmds and len(impls) >= 2:
            parts = {cid: "Command"}
            for d in impls:
                parts[d] = "Concrete Command"
            for oid, other in ctx.classes.items():
                for attr in other.attributes:
                    if any(t in parts for t, _ in ctx.attr_targets(attr)) and oid not in parts:
                        if any(attr.name in m.attr_calls or attr.name in m.iterated_attrs for m in other.methods):
                            parts[oid] = "Invoker"
            ev = [f"abstract {abstract_cmds[0].name}() implemented by {len(impls)} commands"]
            if cls.method("undo"):
                ev.append("supports undo()")
            out.append(PatternMatch("command", parts, ev, 0.85 if cls.name.lower().endswith("command") else 0.7))
            bases_done.add(cid)
    # Name-based families: ...Command classes with an execute-like method
    for cid, cls in ctx.classes.items():
        if cls.name.endswith("Command") and not any(cid in m.participants for m in out) \
                and any(m.name in COMMAND_METHODS for m in cls.methods):
            out.append(PatternMatch("command", {cid: "Command"}, ["name ends with 'Command' and is executable"], 0.6))
    return out


def detect_visitor(ctx: Context) -> list[PatternMatch]:
    out = []
    visitors: dict[str, ClassInfo] = {}
    for cid, cls in ctx.classes.items():
        visits = [m for m in cls.methods if m.name.startswith("visit_") or m.name == "visit"]
        ext = any(b.rsplit(".", 1)[-1] in ("NodeVisitor", "NodeTransformer") for b in cls.bases)
        if len(visits) >= 2 or ext or (visits and any("register" in d or "singledispatch" in d for v in visits for d in v.decorators)):
            visitors[cid] = cls
    elements = {cid: c for cid, c in ctx.classes.items()
                if (acc := c.method("accept")) and any(any(x.startswith("visit") for x in calls) for calls in acc.name_calls.values())}
    for cid, cls in visitors.items():
        if any(cid in ctx.descendants(v) for v in visitors):
            continue  # report on the root visitor only
        parts = {cid: "Visitor"}
        for d in ctx.descendants(cid):
            parts[d] = "Concrete Visitor"
        for e in elements:
            parts.setdefault(e, "Element")
        n = len([m for m in cls.methods if m.name.startswith("visit")])
        ev = [f"{n} visit methods" if n else "extends ast.NodeVisitor"]
        if elements:
            ev.append(f"{len(elements)} elements implement accept(visitor)")
        out.append(PatternMatch("visitor", parts, ev, 0.9 if elements else 0.7))
    if elements and not visitors:
        out.append(PatternMatch("visitor", {e: "Element" for e in elements},
                                ["accept(visitor) double dispatch"], 0.6))
    return out


def detect_iterator(ctx: Context) -> list[PatternMatch]:
    out = []
    for cid, cls in ctx.classes.items():
        if cls.method("__next__") or cls.method("__anext__"):
            parts = {cid: "Iterator"}
            for oid, other in ctx.classes.items():
                it = other.method("__iter__")
                if oid != cid and it and any(_resolve_call(ctx, other, c) == cid for c in it.calls):
                    parts[oid] = "Aggregate"
            out.append(PatternMatch("iterator", parts, ["implements __iter__/__next__ protocol"], 0.85))
    return out


def detect_registry(ctx: Context) -> list[PatternMatch]:
    out = []
    for cid, cls in ctx.classes.items():
        reg_attrs = [a for a in cls.attributes if a.scope == "class" and
                     ((a.type or "").split("[")[0].lower() in ("dict", "list", "set", "defaultdict")
                      or (a.default or "").startswith(("{", "[", "dict(", "defaultdict(")))]
        for a in reg_attrs:
            writers = [m for m in cls.methods if a.name in m.attr_writes or
                       (a.name in m.class_attr_refs and (m.name.startswith(("register", "add")) or m.name == "__init_subclass__"))
                       or (a.name in m.attr_calls and m.name.startswith("register"))]
            if writers and (REGISTRY_ATTR.search(a.name) or any(w.name.startswith("register") or w.name == "__init_subclass__"
                                                               for w in writers)):
                ev = [f"class-level table '{a.name}'", f"populated by {writers[0].name}()"]
                if writers[0].name == "__init_subclass__":
                    ev.append("subclasses register themselves automatically")
                parts = {cid: "Registry"}
                if writers[0].name == "__init_subclass__":
                    for d in ctx.descendants(cid):
                        parts[d] = "Registered"
                out.append(PatternMatch("registry", parts, ev, 0.8))
                break
    return out


def detect_idioms(ctx: Context) -> list[PatternMatch]:
    out = []
    for cid, cls in ctx.classes.items():
        names = {m.name for m in cls.methods}
        if {"__enter__", "__exit__"} <= names or {"__aenter__", "__aexit__"} <= names:
            out.append(PatternMatch("context_manager", {cid: "Context Manager"},
                                    ["implements __enter__/__exit__" if "__enter__" in names else "implements __aenter__/__aexit__"],
                                    1.0))
        if cls.is_data:
            kind = next(s for s in cls.stereotypes if s in ("dataclass", "namedtuple", "typeddict", "model", "attrs"))
            ev = [f"declared as {kind}"]
            if "frozen" in cls.stereotypes:
                ev.append("immutable (frozen) value object")
            out.append(PatternMatch("data_class", {cid: "Value Object" if "frozen" in cls.stereotypes else "Data Class"}, ev, 1.0))
        public = [m for m in cls.methods if not m.name.startswith("_") or m.name == "__call__"]
        if ("protocol" in cls.stereotypes or (cls.is_abstract and public and all(m.is_abstract or m.is_stub for m in public))) \
                and not [a for a in cls.attributes if a.scope == "instance" and a.kind == "field"]:
            impls = ctx.descendants(cid)
            parts = {cid: "Interface"}
            for d in impls:
                parts[d] = "Implementation"
            out.append(PatternMatch("interface", parts,
                                    ["protocol" if "protocol" in cls.stereotypes else "all public methods are abstract",
                                     f"{len(impls)} implementations"], 1.0))
    return out


DETECTORS: list[Callable[[Context], list[PatternMatch]]] = [
    detect_singleton, detect_factories, detect_builder, detect_prototype,
    detect_wrappers, detect_facade,
    detect_observer, detect_strategy_state, detect_template_method, detect_command,
    detect_visitor, detect_iterator, detect_registry, detect_idioms,
]


def detect_patterns(project: Project, min_confidence: float = 0.0) -> list[PatternMatch]:
    ctx = Context(project)
    matches: list[PatternMatch] = []
    seen: dict[tuple[str, frozenset[str]], PatternMatch] = {}
    for det in DETECTORS:
        for m in det(ctx):
            if m.confidence < min_confidence:
                continue
            key = (m.key, frozenset(m.participants))
            if key in seen:
                prev = seen[key]
                prev.evidence += [e for e in m.evidence if e not in prev.evidence]
                prev.confidence = max(prev.confidence, m.confidence)
                continue
            seen[key] = m
            matches.append(m)
    matches.sort(key=lambda m: (CATEGORY_ORDER[CATALOG[m.key][1]], CATALOG[m.key][0], -m.confidence))
    for cls in project.classes.values():
        cls.patterns = []
    for i, m in enumerate(matches):
        for cid, role in m.participants.items():
            project.classes[cid].patterns.append({"key": m.key, "role": role, "match": i, "confidence": m.confidence,
                                                  "support": is_supporting(role)})
    for cls in project.classes.values():
        # Primary roles (the class *is* the pattern) first, then supporting roles, by category.
        cls.patterns.sort(key=lambda p: (CATEGORY_ORDER[CATALOG[p["key"]][1]] == 3,
                                         p["support"], -p["confidence"]))
    project.patterns = matches
    return matches


def is_supporting(role: str) -> bool:
    """True for roles that merely take part in a pattern (e.g. a Product) rather than embody it."""
    return role in {"Real Subject", "Handler (abstract)", "Product", "Product (abstract)", "Leaf", "Component", "Subject", "Adaptee", "Target", "Subsystem",
                    "Element", "Concrete Component", "Implementation", "Registered", "Aggregate", "Observer",
                    "Concrete Observer", "Invoker"}
