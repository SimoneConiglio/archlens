import textwrap

from archlens import analyze

from .conftest import write_pkg


def rels(project, kind):
    return {(r.source.split(".")[-1], r.target.split(".")[-1]) for r in project.relations if r.kind == kind}


def test_modules_and_classes_discovered(zoo):
    assert set(zoo.modules) == {
        "patterns_zoo", "patterns_zoo.shapes", "patterns_zoo.creational",
        "patterns_zoo.structural", "patterns_zoo.behavioral",
    }
    assert "patterns_zoo.shapes.Group" in zoo.classes
    assert zoo.warnings == []


def test_attributes_types_and_origins(zoo):
    group = zoo.classes["patterns_zoo.shapes.Group"]
    children = group.attribute("children")
    assert children.type == "list[Shape]"
    assert children.refs[0].multiplicity == "*"

    shape = zoo.classes["patterns_zoo.shapes.Shape"]
    assert shape.attribute("style").origin == "created"  # self.style = Style()
    assert shape.attribute("origin").origin == "injected"  # from __init__ parameter
    assert shape.is_abstract and "abstract" in shape.stereotypes

    builder = zoo.classes["patterns_zoo.creational.QueryBuilder"]
    assert builder.attribute("_fields").visibility == "protected"
    assert builder.attribute("_limit").type == "int | None"


def test_dataclass_fields_and_stereotypes(zoo):
    point = zoo.classes["patterns_zoo.shapes.Point"]
    assert {"dataclass", "frozen"} <= set(point.stereotypes)
    assert [a.name for a in point.attributes] == ["x", "y"]
    assert all(a.scope == "instance" for a in point.attributes)
    drawing = zoo.classes["patterns_zoo.shapes.Drawing"]
    assert drawing.attribute("root").origin == "created"  # field(default_factory=Group)


def test_relation_kinds(zoo):
    assert ("Circle", "Shape") in rels(zoo, "inheritance")
    assert ("Shape", "Style") in rels(zoo, "composition")
    assert ("Group", "Shape") in rels(zoo, "aggregation")
    assert ("Drawing", "Group") in rels(zoo, "composition")
    assert ("OrderFacade", "Inventory") in rels(zoo, "composition")
    assert ("EventBus", "Observer") in rels(zoo, "aggregation")
    assert ("ShapeFactory", "Circle") in rels(zoo, "dependency")
    # a Protocol is realised, not inherited
    assert all(t != "Observer" for _, t in rels(zoo, "inheritance"))


def test_cross_module_resolution_through_reexports(tmp_path):
    pkg = write_pkg(tmp_path, {
        "__init__.py": "from .core import Engine\n",
        "core.py": "class Engine:\n    pass\n",
        "car.py": textwrap.dedent("""
            import pkg
            from pkg import Engine as E

            class Car:
                def __init__(self) -> None:
                    self.engine = E()
                    self.spare: "pkg.Engine | None" = None
        """),
    })
    p = analyze(pkg)
    assert ("Car", "Engine") in rels(p, "composition")
    car = p.classes["pkg.car.Car"]
    assert car.attribute("spare").refs[0].target == "pkg.core.Engine"


def test_properties_class_vars_and_enums(tmp_path):
    pkg = write_pkg(tmp_path, {"m.py": textwrap.dedent("""
        from enum import Enum
        from typing import ClassVar

        class Color(Enum):
            RED = 1
            GREEN = 2

        class Thing:
            count: ClassVar[int] = 0
            name: str

            def __init__(self):
                self.__secret = 1

            @property
            def size(self) -> int:
                return 1

            @size.setter
            def size(self, v): ...
    """)})
    p = analyze(pkg)
    color = p.classes["pkg.m.Color"]
    assert "enum" in color.stereotypes
    assert [a.kind for a in color.attributes] == ["enum_member", "enum_member"]
    thing = p.classes["pkg.m.Thing"]
    assert thing.attribute("count").scope == "class"
    assert thing.attribute("name").scope == "instance"
    assert thing.attribute("_Thing__secret") is None
    assert thing.attribute("__secret").visibility == "private"
    size = thing.attribute("size")
    assert size.kind == "property" and not size.readonly
    assert thing.method("size") is None


def test_syntax_errors_are_reported_not_fatal(tmp_path):
    pkg = write_pkg(tmp_path, {"good.py": "class A: pass\n", "bad.py": "class (:\n"})
    p = analyze(pkg)
    assert "pkg.good.A" in p.classes
    assert any("bad.py" in w and "syntax error" in w for w in p.warnings)


def test_exclude_globs(tmp_path):
    pkg = write_pkg(tmp_path, {"a.py": "class A: pass\n", "tests/test_a.py": "class TestA: pass\n"})
    p = analyze(pkg, exclude=["tests/*"])
    assert set(p.classes) == {"pkg.a.A"}


def test_single_file(tmp_path):
    f = tmp_path / "solo.py"
    f.write_text("class Base: ...\nclass Child(Base): ...\n")
    p = analyze(f)
    assert ("Child", "Base") in rels(p, "inheritance")


def test_nested_classes(tmp_path):
    pkg = write_pkg(tmp_path, {"m.py": textwrap.dedent("""
        class Outer:
            class Inner:
                pass

            def __init__(self):
                self.inner = Outer.Inner()
    """)})
    p = analyze(pkg)
    assert "pkg.m.Outer.Inner" in p.classes
    assert ("Outer", "Inner") in rels(p, "composition")
