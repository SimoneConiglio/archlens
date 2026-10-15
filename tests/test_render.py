import json
import re
import shutil
import subprocess

import pytest

from archlens import render_site
from archlens.cli import main

from .conftest import ZOO


def load_model(out):
    text = (out / "assets" / "model.js").read_text()
    m = re.fullmatch(r"window\.ARCHLENS_MODEL=(.*);\n", text, re.S)
    assert m
    return json.loads(m.group(1))


def test_render_site_layout(zoo, tmp_path):
    index = render_site(zoo, tmp_path / "out")
    out = index.parent
    for name in ("index.html", "diagram.html", "patterns.html", "model.json",
                 "assets/archlens.js", "assets/archlens.css", "assets/model.js"):
        assert (out / name).is_file(), name
    for mod in zoo.modules:
        assert (out / f"module-{mod}.html").is_file()
    page = (out / "module-patterns_zoo.shapes.html").read_text()
    assert 'data-page="module"' in page and 'data-module="patterns_zoo.shapes"' in page


def test_model_payload(zoo, tmp_path):
    render_site(zoo, tmp_path, title="Zoo <review>")
    model = load_model(tmp_path)
    assert model["meta"]["title"] == "Zoo <review>"
    assert "<title>Zoo &lt;review&gt;</title>" in (tmp_path / "index.html").read_text()
    assert str(ZOO) not in (tmp_path / "assets" / "model.js").read_text(), "absolute paths must not leak"
    group = model["classes"]["patterns_zoo.shapes.Group"]
    assert group["metrics"]["dit"] == 1
    assert "calls" not in group["methods"][0], "detector internals are stripped"
    assert group["attributes"][-1]["targets"] == ["patterns_zoo.shapes.Shape"]
    assert set(model["catalog"]) >= {p["key"] for p in model["patterns"]}
    assert all("support" in x for p in model["patterns"] for x in p["participants"])


def test_cli(tmp_path, capsys):
    assert main([str(ZOO), "-o", str(tmp_path / "r"), "-x", "behavioral.py"]) == 0
    assert "Report written" in capsys.readouterr().out
    model = load_model(tmp_path / "r")
    assert "patterns_zoo.behavioral" not in [m["name"] for m in model["modules"]]

    assert main([str(ZOO), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["classes"]

    assert main([str(tmp_path / "missing")]) == 2


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_client_script_parses(tmp_path, zoo):
    render_site(zoo, tmp_path)
    subprocess.run(["node", "--check", str(tmp_path / "assets" / "archlens.js")], check=True)


def test_package_pages(tmp_path):
    from archlens import analyze

    from .conftest import write_pkg

    pkg = write_pkg(tmp_path / "src", {
        "sub/__init__.py": '"""A sub-package."""\n',
        "sub/a.py": "class A: ...\n",
        "sub/b.py": "from .a import A\nclass B(A): ...\n",
        "lonely/__init__.py": "",
        "lonely/c.py": "class C: ...\n",
    })
    render_site(analyze(pkg), tmp_path / "out")
    model = load_model(tmp_path / "out")
    # only sub-packages grouping classes from several modules get a page; the root is the full diagram
    assert [p["name"] for p in model["packages"]] == ["pkg.sub"]
    assert model["packages"][0] == {"name": "pkg.sub", "docstring": "A sub-package.", "modules": 3, "classes": 2}
    assert 'data-page="package"' in (tmp_path / "out" / "package-pkg.sub.html").read_text()
