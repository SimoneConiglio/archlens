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


PLUGIN_PKG = {
    "meta.py": textwrap.dedent("""
        from abc import ABCMeta

        class Multiton(type):
            _cache: dict = {}

            def __call__(self, *args):
                instance = self._cache.get(self)
                if instance is None:
                    instance = self._cache[self] = super().__call__(*args)
                return instance

        class ABCMultiton(ABCMeta, Multiton):
            pass
    """),
    "factory.py": textwrap.dedent("""
        from importlib.metadata import entry_points
        from typing import Generic, TypeVar
        from .meta import ABCMultiton

        T = TypeVar("T")

        class BaseFactory(Generic[T], metaclass=ABCMultiton):
            def __init__(self) -> None:
                self.__classes: dict[str, type] = {}

            def update(self) -> None:
                for ep in entry_points(group="plugins"):
                    self.__classes[ep.name] = ep.load()

            def get_class(self, name: str) -> type[T]:
                return self.__classes[name]

            def create(self, name: str, **options) -> T:
                cls = self.get_class(name)
                return cls(**options)
    """),
    "solvers.py": textwrap.dedent("""
        from abc import abstractmethod
        from docstring_inheritance import ABCGoogleDocstringInheritanceMeta
        from pydantic import BaseModel
        from .factory import BaseFactory

        class BaseSettings(BaseModel):
            tolerance: float = 1e-6

        class NewtonSettings(BaseSettings):
            max_iter: int = 10

        class BaseSolver(metaclass=ABCGoogleDocstringInheritanceMeta):
            def get_residual(self) -> float:
                return 0.0

        class SolverFactory(BaseFactory[BaseSolver]):
            pass

        class Cache:
            @abstractmethod
            def get_all_entries(self): ...

        class MemoryCache(Cache):
            def get_all_entries(self):
                return []
    """),
}


def test_registry_based_factory_family(tmp_path):
    p = analyze(write_pkg(tmp_path, PLUGIN_PKG))
    r = roles(p)
    assert ("factory", "BaseFactory", "Factory") in r
    assert ("factory", "SolverFactory", "Concrete Factory") in r
    assert ("factory", "BaseSolver", "Product") in r  # from the generic base BaseFactory[BaseSolver]
    assert ("registry", "BaseFactory", "Registry") in r
    reg = next(m for m in p.patterns if m.key == "registry")
    assert any("entry_points" in e for e in reg.evidence)


def test_multiton_metaclass_applies_to_users_and_subclasses(tmp_path):
    p = analyze(write_pkg(tmp_path, PLUGIN_PKG))
    r = roles(p)
    assert ("singleton", "Multiton", "Multiton metaclass") in r
    assert ("singleton", "BaseFactory", "Multiton") in r
    assert ("singleton", "SolverFactory", "Multiton (inherited)") in r
    assert "metaclass" in p.classes["pkg.meta.ABCMultiton"].stereotypes


def test_stereotypes_from_metaclass_and_inheritance(tmp_path):
    p = analyze(write_pkg(tmp_path, PLUGIN_PKG))
    assert "abstract" in p.classes["pkg.solvers.BaseSolver"].stereotypes  # ABC-derived metaclass
    assert "model" in p.classes["pkg.solvers.NewtonSettings"].stereotypes  # inherited pydantic model
    assert ("data_class", "NewtonSettings", "Data Class") in roles(p)


def test_abstract_getter_is_not_a_factory_method(tmp_path):
    p = analyze(write_pkg(tmp_path, PLUGIN_PKG))
    assert not [m for m in p.patterns if "pkg.solvers.Cache" in m.participants and m.key == "factory"]
