"""Command line interface: ``archlens path/to/package -o report/``."""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path

from . import __version__
from .analyzer import analyze
from .patterns import CATALOG, detect_patterns
from .render import build_model, render_site


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="archlens",
        description="Generate interactive HTML class diagrams and design-pattern reports for a Python package.",
    )
    p.add_argument("source", help="package directory, source tree or single .py file to analyse")
    p.add_argument("-o", "--output", default="archlens-report", help="output directory (default: %(default)s)")
    p.add_argument("-t", "--title", help="report title (default: package name)")
    p.add_argument("-x", "--exclude", action="append", default=[], metavar="GLOB",
                   help="exclude files matching a glob relative to the source, e.g. 'tests/*' (repeatable)")
    p.add_argument("--min-confidence", type=float, default=0.0, metavar="X",
                   help="drop pattern matches below this confidence (0-1)")
    p.add_argument("--json", action="store_true", help="print the analysed model as JSON to stdout instead of writing HTML")
    p.add_argument("--no-export", action="store_true",
                   help="hide the 'Download SVG' buttons (for hosting where downloads are blocked)")
    p.add_argument("--open", action="store_true", help="open the report in a web browser when done")
    p.add_argument("-q", "--quiet", action="store_true", help="only print errors")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        project = analyze(args.source, exclude=args.exclude)
    except FileNotFoundError as exc:
        print(f"archlens: {exc}", file=sys.stderr)
        return 2
    if args.min_confidence:
        detect_patterns(project, min_confidence=args.min_confidence)
    if args.json:
        json.dump(build_model(project, args.title), sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0
    index = render_site(project, args.output, title=args.title, export=not args.no_export)
    if not args.quiet:
        n_pat = sum(1 for m in project.patterns if CATALOG[m.key][1] != "idiom")
        print(f"Analysed {len(project.modules)} modules, {len(project.classes)} classes, "
              f"{len(project.relations)} relations, {n_pat} design pattern instances.")
        for w in project.warnings:
            print(f"  warning: {w}", file=sys.stderr)
        print(f"Report written to {index}")
    if args.open:
        webbrowser.open(Path(index).resolve().as_uri())
    return 0
