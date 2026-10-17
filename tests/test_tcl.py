import shutil
import subprocess
import textwrap

import pytest

from archlens import analyze
from archlens.languages.tcl import parse_list, parse_script

from .conftest import ROOT

TCL_ZOO = ROOT / "examples" / "tcl_zoo"

EXPECTED = [
    ("singleton", "Config", "Singleton"),
    ("factory", "ShapeFactory", "Factory"),
    ("builder", "QueryBuilder", "Builder"),
    ("prototype", "Shape", "Prototype"),
    ("adapter", "LegacyStorageAdapter", "Adapter"),
    ("decorator", "CompressionDecorator", "Decorator"),
    ("composite", "Group", "Composite"),
    ("proxy", "LazyDataSource", "Proxy"),
    ("facade", "OrderFacade", "Facade"),
    ("observer", "EventBus", "Subject"),
    ("strategy", "Sorter", "Context"),
    ("strategy", "SortStrategy", "Strategy"),
    ("state", "TrafficLight", "Context"),
    ("state", "TrafficState", "State"),
    ("template_method", "Report", "Abstract Class"),
    ("command", "CommandHistory", "Invoker"),
    ("visitor", "AreaVisitor", "Visitor"),
    ("chain", "Handler", "Handler"),
]


@pytest.fixture(scope="module")
def zoo():
    return analyze(TCL_ZOO)


def roles(project):
    return {(m.key, cid.split("::")[-1], role) for m in project.patterns for cid, role in m.participants.items()}


@pytest.mark.parametrize("key,cls,role", EXPECTED)
def test_tcl_zoo_patterns(zoo, key, cls, role):
    assert (key, cls, role) in roles(zoo)


@pytest.mark.skipif(shutil.which("tclsh") is None, reason="tclsh not installed")
def test_tcl_zoo_runs():
    out = subprocess.run(["tclsh", str(TCL_ZOO / "demo.tcl")], capture_output=True, text=True, check=True).stdout
    assert "area via visitor: 7.14" in out and "chain: ok" in out


def test_untyped_members_are_inferred(zoo):
    by_name = {c.name: c for c in zoo.classes.values()}
    sorter = by_name["Sorter"].attribute("strategy")
    assert sorter.type == "SortStrategy" and sorter.origin == "injected"  # from the parameter name
    assert by_name["Group"].attribute("children").type == "list of Shape"  # from $child area
    assert by_name["TrafficLight"].attribute("state").type == "TrafficState"  # created Red, reassigned
    assert by_name["Handler"].attribute("successor").type == "Handler"  # self-typed link
    assert by_name["OrderFacade"].attribute("inventory").origin == "created"


def test_classes_namespaces_and_definitions(zoo):
    by_name = {c.name: c for c in zoo.classes.values()}
    facade = by_name["OrderFacade"]
    assert facade.namespace == "zoo" and facade.language == "tcl"
    assert [b for b in facade.bases] == ["Logging"]  # added later by oo::define ... mixin
    assert "mixin" in by_name["Logging"].stereotypes
    assert by_name["Shape"].docstring == "Abstract component of the shape tree."
    assert by_name["Config"].method("instance").is_classmethod
    assert by_name["LazyDataSource"].method("Load").visibility == "protected"  # unexported (capitalised)


def test_tcl9_class_kinds_and_definitions(tmp_path):
    (tmp_path / "modern.tcl").write_text(textwrap.dedent("""
        oo::abstract create Shape {
            method area {} { error "abstract method" }
        }
        oo::singleton create Registry {
            variable items
            constructor {} { set items [dict create] }
            method add {name obj} { dict set items $name $obj }
            private method Check {} { return 1 }
            classmethod describe {} { return registry }
        }
        oo::class create Meta { superclass oo::class }
        Meta create Widget {
            method draw {} { return }
            unexport draw
            forward show my draw
        }
        oo::define Widget method resize {w h} { return [self] }
        # a comment with an unbalanced { brace
        oo::class create Long \\
            { method x {} {} }
    """))
    p = analyze(tmp_path)
    by_name = {c.name: c for c in p.classes.values()}
    assert "abstract" in by_name["Shape"].stereotypes
    assert ("singleton", "Registry", "Singleton") in roles(p)
    assert by_name["Registry"].method("Check").visibility == "private"
    assert by_name["Registry"].method("describe").is_classmethod
    assert "metaclass" in by_name["Meta"].stereotypes
    widget = by_name["Widget"]
    assert widget.metaclass_id == by_name["Meta"].id
    assert widget.method("draw").visibility == "protected"
    assert widget.method("show").self_calls == ["draw"]
    assert widget.method("resize").returns_self
    assert by_name["Long"].method("x") is not None


def test_parser_handles_tcl_syntax():
    cmds = parse_script('set a "x [list 1 {2 3}] y"; puts {a {b} c}\n# comment ; {\nfoo {*}$args [bar\n baz]')
    assert [c.name for c in cmds] == ["set", "puts", "foo"]
    assert cmds[0].words[2].kind == "quote" and cmds[0].words[2].text == "x [list 1 {2 3}] y"
    assert cmds[1].words[1].text == "a {b} c"
    assert cmds[2].words[1].expand and cmds[2].words[2].text == "[bar\n baz]"
    assert cmds[2].line == 3
    assert parse_list("a {b c} \"d e\" {}") == ["a", "b c", "d e", ""]


def test_tcloo_dialects(tmp_path):
    """Wrappers such as clay::define create or extend classes from a TclOO definition body."""
    (tmp_path / "app.tcl").write_text(textwrap.dedent("""
        ::clay::define ::app::base {
            method render {} { error "abstract method" }
        }
        ::clay::define ::app::page {
            superclass ::app::base
            Variable title {}
            method render {} { return [my title] }
        }
        ::clay::define ::app::notes { the body has no class definition commands }
    """))
    p = analyze(tmp_path)
    by_name = {c.name: c for c in p.classes.values()}
    assert set(by_name) == {"base", "page"}
    assert by_name["page"].base_ids == [by_name["base"].id]
    assert by_name["page"].decorators == ["defined with clay::define"]
    assert by_name["base"].is_abstract
