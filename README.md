# ArchLens

**Static architecture review for Python packages.** Point ArchLens at a package and it generates a
self-contained HTML report with interactive UML class diagrams — every class with all of its
attributes and methods, connected by inheritance, composition, aggregation and dependency edges — and
**colour-coded design patterns** detected from the code.

```bash
pip install -e .
archlens path/to/your_package -o report/
open report/index.html
```

No code is imported or executed: the source is parsed with the standard-library `ast` module, so it is
safe to run on any code base. There are **no runtime dependencies**, and the report works offline
(no CDN, no server) — open it from disk, attach it to a CI run, or publish it on any static host.

## What you get

| Page | Contents |
|---|---|
| `index.html` | Overview: counts, pattern distribution, most-connected classes (fan-in/out, inheritance depth), module table |
| `diagram.html` | Whole-package class diagram, with module filter |
| `module-<name>.html` | One diagram per module, plus neighbouring classes from other modules as dashed "context" boxes |
| `patterns.html` | Every detected pattern instance: participants and their roles, evidence, confidence, and an on-demand mini diagram |
| `model.json` | The extracted model, for your own tooling |

### Interactive diagrams

* **UML class boxes**: stereotypes (`«abstract»`, `«interface»`, `«dataclass»`, `«protocol»`, `«enum»`…),
  attributes with types and visibility (`+` public, `#` protected, `-` private, `/` property,
  underlined = class-level), and method signatures (abstract methods in italics).
* **Relations** with standard UML notation:

  | Edge | Meaning | Inferred from |
  |---|---|---|
  | solid line, hollow triangle | inheritance | base classes |
  | dashed line, hollow triangle | realisation | subclassing a `typing.Protocol` |
  | filled diamond | composition (owns) | `self.x = Thing()`, `field(default_factory=Thing)`, dataclass fields |
  | hollow diamond | aggregation (has) | `self.x = x` from a constructor parameter, typed attributes |
  | dashed arrow | dependency (uses) | type hints in signatures, classes instantiated in method bodies |

  Edge labels show the attribute name and multiplicity (`0..1` for `Optional`, `0..*` for collections).
* **Pan** (drag background), **zoom** (wheel / buttons), **drag boxes** to rearrange, **click** a class
  to highlight its neighbourhood and open the details panel (docstring, metrics, every attribute and
  method, relations, pattern evidence), **double-click** to focus.
* Toggle attributes, methods, private members, dunder methods, labels and each relation kind; the
  layered layout re-flows automatically. Search with `/`, reset with `Esc`, fit with `f`.
* **Download SVG** of the current view. Light and dark themes.
* Deep links: `module-x.html#class=pkg.x.MyClass`, `diagram.html#pattern=observer,strategy`.

### Colour-coded design patterns

Hue families follow the pattern category — **warm** for creational, **blue/teal** for structural,
**green/purple** for behavioural, **neutral** for Python idioms. Each class header is tinted with the
pattern it *embodies*; chips list every pattern it takes part in (solid = core role such as
*Decorator*, outlined = supporting role such as *Component* or *Product*). Pattern names are always
written on the chip, so colour is never the only cue. Click a pattern in the legend to highlight its
participants.

| Category | Patterns detected |
|---|---|
| Creational | Singleton, Factory / Factory Method, Abstract Factory, Builder, Prototype |
| Structural | Adapter, Decorator, Composite, Proxy, Facade |
| Behavioural | Observer, Strategy, State, Template Method, Command, Visitor, Iterator, Chain of Responsibility |
| Python idioms | Registry, Context Manager, Data Class / Value Object, Interface (ABC / Protocol) |

Detection is heuristic and structural: it looks at who inherits from whom, which attributes hold which
types (and whether they are created internally or injected), and what methods do — return `self`,
iterate over a subscriber list, forward the same call to a wrapped object, call abstract steps, cache a
class-level instance, and so on. Every match carries human-readable **evidence** and a **confidence**
score; use `--min-confidence` to keep only strong matches.
[`examples/patterns_zoo`](examples/patterns_zoo) contains a reference implementation of every pattern
and doubles as the test fixture.

## Command line

```
archlens SOURCE [-o OUT] [-t TITLE] [-x GLOB ...] [--min-confidence X] [--json] [--open] [-q]
```

* `SOURCE` — a package directory (with `__init__.py`), a source tree (e.g. `src/`) or a single `.py` file.
* `-x/--exclude` — skip files matching a glob relative to the source, e.g. `-x 'tests/*' -x '*_pb2.py'`.
* `--json` — print the model as JSON instead of writing HTML.
* `python -m archlens …` works too.

### From Python

```python
from archlens import analyze, render_site

project = analyze("src/mypkg", exclude=["tests/*"])
for match in project.patterns:
    print(match.key, match.participants, match.confidence)
render_site(project, "report/")
```

## How it works

```
src/archlens/
├── analyzer.py   AST → classes, attributes (type, origin, scope, visibility), methods, behavioural facts;
│                 import/re-export resolution; relation building
├── patterns.py   pattern catalogue (names, categories, colours) and the detectors
├── render.py     model → JSON + page shells, metrics (DIT, NOC, fan-in/out)
├── cli.py
└── static/       archlens.js (layered layout, SVG diagrams, pages) and archlens.css
```

The analyser produces a language-neutral model (`model.py`), so other languages can be added later as
new front-ends feeding the same detectors and renderer.

## Development

```bash
pip install -e '.[dev]'
pytest
archlens examples/patterns_zoo -o /tmp/zoo-report
```

## Limitations

* Static analysis only: attributes created dynamically (`setattr`, `__dict__` updates) and types that
  can only be known at run time are not seen. Type hints greatly improve results.
* Only classes are diagrammed; module-level functions are counted but not drawn.
* Pattern detection is a review aid, not a proof — treat low-confidence matches as hints.
