"""Generate the static HTML report: overview, full diagram, per-module diagrams and a pattern catalogue.

The pages are self-contained (no CDN, no server): the class model is written to
``assets/model.js`` and the interactive diagrams are drawn client-side by
``assets/archlens.js`` with plain SVG, so the output can be opened straight from
disk, archived as a CI artifact or served by any static host.
"""

from __future__ import annotations

import html
import json
import shutil
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any

from . import __version__
from .model import Project
from .patterns import CATALOG, is_supporting

STATIC_FILES = ("archlens.js", "archlens.css")
# Behavioural facts only needed by the pattern detectors; not shipped to the browser.
_DETECTOR_FACTS = ("self_calls", "attr_calls", "name_calls", "iterated_attrs", "calls", "class_attr_refs",
                   "attr_writes", "ref_names", "returns_self", "raises_not_implemented")


def _metrics(project: Project) -> dict[str, dict[str, int]]:
    fan_in: dict[str, set[str]] = {c: set() for c in project.classes}
    fan_out: dict[str, set[str]] = {c: set() for c in project.classes}
    for r in project.relations:
        if r.kind in ("inheritance", "realization") or r.source == r.target:
            continue
        fan_out[r.source].add(r.target)
        fan_in[r.target].add(r.source)

    depth: dict[str, int] = {}

    def dit(cid: str, seen: frozenset[str] = frozenset()) -> int:
        if cid in depth:
            return depth[cid]
        bases = [b for b in project.classes[cid].base_ids if b and b not in seen and b != cid]
        depth[cid] = 0 if not bases else 1 + max(dit(b, seen | {cid}) for b in bases)
        return depth[cid]

    out = {}
    for cid, cls in project.classes.items():
        out[cid] = {
            "dit": dit(cid),
            "noc": len(cls.subclasses),
            "fan_in": len(fan_in[cid]),
            "fan_out": len(fan_out[cid]),
            "methods": len(cls.methods),
            "attributes": len([a for a in cls.attributes if a.kind != "enum_member"]),
            "loc": (cls.end_lineno - cls.lineno + 1) if cls.end_lineno else 0,
        }
    return out


def build_model(project: Project, title: str | None = None) -> dict[str, Any]:
    data = project.to_dict()
    metrics = _metrics(project)
    for cid, cls in data["classes"].items():
        cls["metrics"] = metrics[cid]
        for m in cls["methods"]:
            for key in _DETECTOR_FACTS:
                m.pop(key, None)
        for a in cls["attributes"]:
            a["targets"] = sorted({r["target"] for r in a.pop("refs") if r["target"]})
    patterns = []
    for m in data["patterns"]:
        name, category, color, _ = CATALOG[m["key"]]
        patterns.append({
            "key": m["key"],
            "name": name,
            "category": category,
            "confidence": round(m["confidence"], 2),
            "participants": [{"id": cid, "role": role, "support": is_supporting(role)}
                             for cid, role in m["participants"].items()],
            "evidence": m["evidence"],
        })
    data["patterns"] = patterns
    data["modules"] = sorted(data["modules"].values(), key=lambda m: m["name"])
    data["catalog"] = {
        key: {"name": n, "category": c, "color": col, "description": d}
        for key, (n, c, col, d) in CATALOG.items()
    }
    data["meta"] = {
        "title": title or project.name,
        "version": __version__,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
    data.pop("root", None)  # do not leak absolute local paths into the report
    return data


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="generator" content="ArchLens {version}">
<link rel="stylesheet" href="assets/archlens.css">
<script>try{{var t=localStorage.getItem('archlens-theme');if(t)document.documentElement.dataset.theme=t;}}catch(e){{}}</script>
</head>
<body data-page="{page}" data-module="{module}">
<noscript><p style="padding:2rem">ArchLens reports need JavaScript enabled to draw the diagrams.</p></noscript>
<div id="app"></div>
<script src="assets/model.js"></script>
<script src="assets/archlens.js"></script>
</body>
</html>
"""


def module_page_name(module: str) -> str:
    return f"module-{module}.html"


def render_site(project: Project, out_dir: str | Path, title: str | None = None) -> Path:
    """Write the full report into ``out_dir`` and return the path of ``index.html``."""
    out = Path(out_dir)
    assets = out / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    static = resources.files("archlens") / "static"
    for name in STATIC_FILES:
        with resources.as_file(static / name) as src:
            shutil.copyfile(src, assets / name)

    model = build_model(project, title)
    payload = json.dumps(model, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    (assets / "model.js").write_text(f"window.ARCHLENS_MODEL={payload};\n", encoding="utf-8")

    name = html.escape(model["meta"]["title"])

    def page(file: str, kind: str, label: str, module: str = "") -> None:
        (out / file).write_text(
            PAGE.format(title=f"{label} · {name}" if label else name, version=__version__,
                        page=kind, module=html.escape(module, quote=True)),
            encoding="utf-8",
        )

    page("index.html", "overview", "")
    page("diagram.html", "diagram", "Class diagram")
    page("patterns.html", "patterns", "Design patterns")
    for mod in model["modules"]:
        page(module_page_name(mod["name"]), "module", mod["name"], mod["name"])
    (out / "model.json").write_text(json.dumps(model, indent=2, ensure_ascii=False), encoding="utf-8")
    return out / "index.html"
