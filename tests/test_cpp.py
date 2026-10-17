import textwrap

import pytest

pytest.importorskip("tree_sitter_cpp")

from archlens import analyze  # noqa: E402

from .conftest import ROOT  # noqa: E402

CPP_ZOO = ROOT / "examples" / "cpp_zoo"

EXPECTED = [
    ("singleton", "Config", "Singleton"),
    ("factory", "ShapeFactory", "Factory"),
    ("factory", "PluginRegistry", "Factory"),
    ("registry", "PluginRegistry", "Registry"),
    ("abstract_factory", "WidgetFactory", "Abstract Factory"),
    ("builder", "QueryBuilder", "Builder"),
    ("prototype", "Shape", "Prototype"),
    ("prototype", "Group", "Concrete Prototype"),
    ("adapter", "LegacyStorageAdapter", "Adapter"),
    ("decorator", "CompressionDecorator", "Decorator"),
    ("composite", "Group", "Composite"),
    ("proxy", "LazyDataSource", "Proxy"),
    ("facade", "OrderFacade", "Facade"),
    ("observer", "EventBus", "Subject"),
    ("observer", "AuditLog", "Concrete Observer"),
    ("strategy", "Sorter", "Context"),
    ("state", "TrafficLight", "Context"),
    ("template_method", "Report", "Abstract Class"),
    ("command", "CommandHistory", "Invoker"),
    ("visitor", "ShapeVisitor", "Visitor"),
    ("visitor", "Circle", "Element"),
    ("iterator", "Iterator", "Iterator"),
    ("iterator", "Range", "Aggregate"),
    ("chain", "Handler", "Handler"),
    ("data_class", "Point", "Data Class"),
    ("interface", "SortStrategy", "Interface"),
]


@pytest.fixture(scope="module")
def zoo():
    return analyze(CPP_ZOO)


def roles(project):
    return {(m.key, cid.split("::")[-1], role) for m in project.patterns for cid, role in m.participants.items()}


def rels(project, kind):
    return {(r.source.split("::")[-1], r.target.split("::")[-1], r.label) for r in project.relations if r.kind == kind}


@pytest.mark.parametrize("key,cls,role", EXPECTED)
def test_cpp_zoo_patterns(zoo, key, cls, role):
    assert (key, cls, role) in roles(zoo)


def test_modules_are_files_and_directories_are_packages(zoo):
    assert "shapes/shape.hpp" in zoo.modules and zoo.modules["shapes"].is_package
    group = next(c for c in zoo.classes.values() if c.name == "Group")
    assert group.namespace == "zoo::shapes" and group.language == "cpp"


def test_ownership_drives_composition_and_aggregation(zoo):
    comp, agg = rels(zoo, "composition"), rels(zoo, "aggregation")
    assert ("Group", "Shape", "children_") in comp  # std::vector<std::unique_ptr<Shape>>
    assert ("Shape", "Point", "origin_") in comp  # value member
    assert ("LegacyStorageAdapter", "LegacyStorage", "storage_") in agg  # reference
    assert ("EventBus", "Observer", "observers_") in agg  # vector of raw pointers
    children = next(c for c in zoo.classes.values() if c.name == "Group").attribute("children_")
    assert children.refs[0].multiplicity == "*" and children.ownership == "owned"


def test_constructor_initialisers_set_member_origin(zoo):
    decorator = next(c for c in zoo.classes.values() if c.name == "CompressionDecorator")
    assert decorator.attribute("wrapped_").origin == "injected"  # wrapped_(std::move(wrapped))
    light = next(c for c in zoo.classes.values() if c.name == "TrafficLight")
    assert light.attribute("state_").origin == "created"  # state_(std::make_unique<Red>())


def test_out_of_line_bodies_are_attached(zoo):
    group = next(c for c in zoo.classes.values() if c.name == "Group")
    area = group.method("area")
    assert "children_" in area.iterated_attrs and area.attr_calls["children_"] == ["area"]
    config = next(c for c in zoo.classes.values() if c.name == "Config")
    assert config.method("get").attr_calls == {"values_": ["find", "end"]}


def test_method_details(zoo):
    shape = next(c for c in zoo.classes.values() if c.name == "Shape")
    area = shape.method("area")
    assert area.is_abstract and area.returns == "double" and "const" in area.decorators
    assert shape.method("~Shape").kind == "destructor"
    assert "abstract" in shape.stereotypes
    config = next(c for c in zoo.classes.values() if c.name == "Config")
    ctors = [m for m in config.methods if m.kind == "constructor"]
    assert [(len(m.params), m.visibility, "= delete" in m.decorators) for m in ctors] == [(1, "public", True), (0, "private", False)]


def test_language_features(tmp_path):
    (tmp_path / "lib.hpp").write_text(textwrap.dedent("""
        #include <memory>
        #include <vector>
        namespace lib {
        template <typename Derived>
        class Base { public: void run() { static_cast<Derived*>(this)->step(); } };

        class Engine;
        using EnginePtr = std::shared_ptr<Engine>;

        class Engine { public: enum class Mode { Fast, Safe }; struct Part { int id; }; };

        class Car final : public Base<Car> {
         public:
          void step();
         private:
          EnginePtr engine_;
          std::vector<Engine::Part> parts_;
          Engine::Mode mode_ = Engine::Mode::Fast;
        };
        }  // namespace lib
    """))
    p = analyze(tmp_path)
    car = next(c for c in p.classes.values() if c.name == "Car")
    assert car.base_ids == ["lib.hpp::lib::Base"]
    assert [r.target for r in car.base_args] == ["lib.hpp::lib::Car"]  # CRTP argument
    assert "final" in car.stereotypes
    assert car.attribute("engine_").refs[0].target == "lib.hpp::lib::Engine"  # through the alias
    assert car.attribute("engine_").ownership == "shared"
    assert car.attribute("parts_").refs[0].target == "lib.hpp::lib::Engine::Part"
    mode = p.classes["lib.hpp::lib::Engine::Mode"]
    assert "enum" in mode.stereotypes and [a.name for a in mode.attributes] == ["Fast", "Safe"]
    assert "template" in p.classes["lib.hpp::lib::Base"].stereotypes
    assert ("Car", "Engine", "engine_") in rels(p, "aggregation")


def test_real_world_cpp_idioms(tmp_path):
    """Regressions found on LevelDB: export macros, nested classes defined out of line, cursor iterators."""
    (tmp_path / "db.h").write_text(textwrap.dedent("""
        #define LEVELDB_EXPORT
        namespace leveldb {
        class LEVELDB_EXPORT Iterator {
         public:
          virtual ~Iterator();
          virtual bool Valid() const = 0;
          virtual void Next() = 0;
        };
        class LEVELDB_EXPORT Table {
         public:
          Iterator* NewIterator() const;
          uint64_t NewId();
         private:
          struct Rep;
          Rep* rep_;
        };
        struct Node { Node* next_; int value; };
        struct Callbacks { void* state; void (*fn)(void*); void Run() { (*fn)(state); } };
        }
    """))
    (tmp_path / "table.cc").write_text(textwrap.dedent("""
        #include "db.h"
        namespace leveldb {
        struct Table::Rep { int options; };
        class TableIter : public Iterator {
         public:
          bool Valid() const override { return true; }
          void Next() override {}
        };
        Iterator* Table::NewIterator() const { return new TableIter(); }
        }
    """))
    p = analyze(tmp_path)
    names = {c.name for c in p.classes.values()}
    assert {"Iterator", "Table", "TableIter", "Rep"} <= names
    rep = next(c for c in p.classes.values() if c.name == "Rep")
    assert rep.qualname == "Table::Rep" and rep.file == "table.cc"
    r = roles(p)
    assert ("iterator", "Iterator", "Iterator") in r and ("iterator", "TableIter", "Concrete Iterator") in r
    assert ("iterator", "Table", "Aggregate") in r
    assert not any(m.key == "chain" for m in p.patterns), "an intrusive linked list is not a chain of responsibility"
    assert ("factory", "Table", "Factory") in r  # NewIterator() returns new TableIter() as an Iterator*
    assert not any(c.endswith("Callbacks") for m in p.patterns for c in m.participants), \
        "calls through function pointers are not factories"


def test_blank_macros_preserves_offsets():
    from archlens.languages.cpp import blank_macros

    src = b"class API_EXPORT __declspec(dllexport) Foo : public Bar {\n  Q_OBJECT\n};\n"
    out = blank_macros(src)
    assert len(out) == len(src) and out.count(b"\n") == src.count(b"\n")
    assert out.split() == [b"class", b"Foo", b":", b"public", b"Bar", b"{", b"};"]
