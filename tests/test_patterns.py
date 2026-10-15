import textwrap

import pytest

from archlens import analyze
from archlens.patterns import CATALOG

from .conftest import write_pkg

EXPECTED = [
    ("singleton", "AppConfig", "Singleton"),
    ("singleton", "SingletonMeta", "Singleton metaclass"),
    ("singleton", "Logger", "Singleton"),
    ("factory", "ShapeFactory", "Factory"),
    ("abstract_factory", "WidgetFactory", "Abstract Factory"),
    ("abstract_factory", "DarkWidgetFactory", "Concrete Factory"),
    ("builder", "QueryBuilder", "Builder"),
    ("builder", "Query", "Product"),
    ("prototype", "Shape", "Prototype"),
    ("adapter", "LegacyStorageAdapter", "Adapter"),
    ("adapter", "LegacyStorage", "Adaptee"),
    ("decorator", "CompressionDecorator", "Decorator"),
    ("composite", "Group", "Composite"),
    ("composite", "Circle", "Leaf"),
    ("proxy", "LazyDataSource", "Proxy"),
    ("proxy", "FileDataSource", "Real Subject"),
    ("facade", "OrderFacade", "Facade"),
    ("observer", "EventBus", "Subject"),
    ("strategy", "Sorter", "Context"),
    ("strategy", "QuickSort", "Concrete Strategy"),
    ("state", "TrafficLight", "Context"),
    ("state", "Red", "Concrete State"),
    ("template_method", "Report", "Abstract Class"),
    ("command", "Command", "Command"),
    ("command", "CommandHistory", "Invoker"),
    ("visitor", "ShapeVisitor", "Visitor"),
    ("visitor", "Circle", "Element"),
    ("iterator", "ShapeIterator", "Iterator"),
    ("chain", "Handler", "Handler"),
    ("chain", "AuthHandler", "Concrete Handler"),
    ("registry", "PluginRegistry", "Registry"),
    ("context_manager", "Transaction", "Context Manager"),
    ("data_class", "Point", "Value Object"),
    ("data_class", "Style", "Data Class"),
    ("interface", "Observer", "Interface"),
]


def roles(project):
    out = set()
    for m in project.patterns:
        for cid, role in m.participants.items():
            out.add((m.key, cid.split(".")[-1], role))
    return out


@pytest.mark.parametrize("key,cls,role", EXPECTED)
def test_zoo_pattern_detected(zoo, key, cls, role):
    assert (key, cls, role) in roles(zoo)


def test_every_catalog_pattern_is_exercised(zoo):
    assert {m.key for m in zoo.patterns} == set(CATALOG)


def test_class_pattern_annotations_are_sorted_core_first(zoo):
    for cls in zoo.classes.values():
        order = [(CATALOG[p["key"]][1] == "idiom", p["support"], -p["confidence"]) for p in cls.patterns]
        assert order == sorted(order), cls.id
    group = zoo.classes["patterns_zoo.shapes.Group"].patterns
    assert group[0] == {**group[0], "key": "composite", "role": "Composite", "support": False}


def test_plain_code_has_no_gof_patterns(tmp_path):
    pkg = write_pkg(tmp_path, {"m.py": textwrap.dedent("""
        class User:
            def __init__(self, name: str, age: int) -> None:
                self.name = name
                self.age = age

            def greet(self) -> str:
                return f"hi {self.name}"

        class Repo:
            def __init__(self) -> None:
                self.users: list[User] = []

            def add(self, user: User) -> None:
                self.users.append(user)
    """)})
    p = analyze(pkg)
    gof = [m for m in p.patterns if CATALOG[m.key][1] != "idiom"]
    assert gof == []


def test_concrete_created_collaborator_is_not_strategy(tmp_path):
    pkg = write_pkg(tmp_path, {"m.py": textwrap.dedent("""
        class Queue:
            def put(self, x): ...
        class LifoQueue(Queue): ...
        class PriorityQueue(Queue): ...

        class Worker:
            def __init__(self):
                self.q = Queue()

            def push(self, x):
                self.q.put(x)
    """)})
    assert not [m for m in analyze(pkg).patterns if m.key == "strategy"]


def test_min_confidence_filter(zoo):
    from archlens.patterns import detect_patterns

    project = analyze(zoo.root)
    detect_patterns(project, min_confidence=0.95)
    assert project.patterns and all(m.confidence >= 0.95 for m in project.patterns)
