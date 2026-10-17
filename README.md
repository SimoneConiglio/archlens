# ArchLens

**Static architecture review for Python, C++ and Tcl/TclOO code.** Point ArchLens at a source tree and it generates a
self-contained HTML report with interactive UML class diagrams — every class with all of its
attributes and methods, connected by inheritance, composition, aggregation and dependency edges — and
**colour-coded design patterns** detected from the code.

```bash
pip install -e .
archlens path/to/your_package -o report/
open report/index.html
```

No code is imported, compiled or executed: sources are only parsed, so it is safe to run on any code base.
Python and Tcl support have **no runtime dependencies**; C++ uses the tree-sitter grammar
(`pip install 'archlens[cpp]'`) and needs no compiler, include paths or build flags. The report works offline
(no CDN, no server) — open it from disk, attach it to a CI run, or publish it on any static host.

## What you get

| Page | Contents |
|---|---|
| `index.html` | Overview: counts, pattern distribution, most-connected classes (fan-in/out, inheritance depth), module table |
| `diagram.html` | Whole-package class diagram, with module filter |
| `package.html#m=<name>` | One diagram per sub-package (e.g. `mypkg.solvers`) — the most useful level for large code bases |
| `module.html#m=<name>` | One diagram per module, plus neighbouring classes from other modules as dashed "context" boxes |
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
* Deep links: `module.html#m=pkg.x&class=pkg.x.MyClass`, `diagram.html#pattern=observer,strategy`.
* The whole report is a handful of files (one page per view kind plus `assets/`), whatever the size of the
  code base; `--no-export` hides the SVG download button for hosts that block downloads.

### Colour-coded design patterns

Hue families follow the pattern category — **warm** for creational, **blue/teal** for structural,
**green/purple** for behavioural, **neutral** for Python idioms. Each class header is tinted with the
pattern it *embodies*; chips list every pattern it takes part in (solid = core role such as
*Decorator*, outlined = supporting role such as *Component* or *Product*). Pattern names are always
written on the chip, so colour is never the only cue. Click a pattern in the legend to highlight its
participants.

| Category | Patterns detected |
|---|---|
| Creational | Singleton / Multiton (incl. caching metaclasses), Factory / Factory Method (incl. registry-based plugin factories), Abstract Factory, Builder, Prototype |
| Structural | Adapter, Decorator, Composite, Proxy, Facade |
| Behavioural | Observer, Strategy, State, Template Method, Command, Visitor, Iterator, Chain of Responsibility |
| Python idioms | Registry (incl. plugin discovery via subclasses / entry points), Context Manager, Data Class / Value Object (dataclasses, attrs, NamedTuple, pydantic models), Interface (ABC / Protocol) |

Detection is heuristic and structural: it looks at who inherits from whom, which attributes hold which
types (and whether they are created internally or injected), and what methods do — return `self`,
iterate over a subscriber list, forward the same call to a wrapped object, call abstract steps, cache a
class-level instance, and so on. Every match carries human-readable **evidence** and a **confidence**
score; use `--min-confidence` to keep only strong matches.
[`examples/patterns_zoo`](examples/patterns_zoo), [`examples/cpp_zoo`](examples/cpp_zoo) and
[`examples/tcl_zoo`](examples/tcl_zoo) implement the patterns in each language (the C++ one compiles, the Tcl
one runs with `tclsh examples/tcl_zoo/demo.tcl`) and double as test fixtures.

### Real-world check: GEMSEO

On [GEMSEO](https://gitlab.com/gemseo/dev/gemseo) 6.3.3 (966 modules, 951 classes) the analysis takes ~3.5 s
and recovers the library's architecture from source alone, for example:

* **Factory + Registry**: `BaseFactory.create()` instantiates classes discovered through `entry_points()`,
  specialised by 41 concrete factories, each paired with its product (`MDAFactory → BaseMDA`,
  `PostFactory → BasePost`, …) read from the generic base `BaseFactory[Product]`.
* **Multiton**: the `BaseABCMultiton` metaclass caching instances of 62 classes (all factories, DOE libraries).
* **Template Method**: `execute() → _run()`, `learn() → _learn()`, `BaseMDA._execute() → _solve()`,
  `BasePost.execute() → _plot()`.
* **Strategy**: `BaseScenario → BaseFormulation` (MDF, IDF, BiLevel, …), `BaseDiscipline → BaseCache`,
  `SurrogateDiscipline → BaseRegressor`.
* **Composite**: `MDASequential`, `ProcessDiscipline`, the ML transformer `Pipeline`.
* **Observer**: `ExecutionStatus` / `Monitoring` observers and the MDA iteration callbacks.

## Languages

Every language feeds the same model, relations and pattern detectors, so reports look and behave the same.
A source tree containing several languages produces one combined report (`-l/--language` restricts it).

| | Python | C++ | Tcl / TclOO |
|---|---|---|---|
| Parser | standard-library `ast` | tree-sitter C++ grammar | built-in Tcl parser (Dodekalogue rules) |
| Classes | classes, nested classes, dataclasses, enums, protocols, pydantic models | classes, structs, unions, enums, templates, nested classes (also defined out of line) | `oo::class`, `oo::abstract`, `oo::singleton`, user metaclasses, `oo::define`, dialects such as `clay::define` |
| Inheritance | bases, metaclasses | public/protected/private/virtual bases, CRTP arguments | `superclass`, `mixin` |
| Members | annotations, `self.x = …`, properties | data members with access, `static`, `const`; methods with `virtual`, `= 0`, `override`, `const`; out-of-line bodies from `.cpp` files | `variable`, `property`, `method`, `self method`, `classmethod`, `private`, `forward`, `export`/`unexport` |
| Composition vs aggregation | created inside (`X()`) vs injected | ownership: value / `unique_ptr` / `optional` vs pointer / reference / `shared_ptr` | `[X new]` vs constructor parameter |
| Types of members | annotations and assignments | declared types, through `using`/`typedef` aliases | inferred: type checks, names (`sortStrategy` → `SortStrategy`) and usage (methods called on the variable) |

Modules are files (`geo/shape.hpp`) and directories are packages for C++ and Tcl. Export macros such as
`class LEVELDB_EXPORT DB` are understood without running a preprocessor.

### Real-world checks

| Code base | Size | Highlights |
|---|---|---|
| [GEMSEO](https://gitlab.com/gemseo/dev/gemseo) 6.3.3 (Python) | 951 classes, 3.5 s | registry-based `BaseFactory` with 41 concrete factories, Multiton metaclass, `execute → _run` template methods, scenario → formulation strategy |
| [LevelDB](https://github.com/google/leveldb) (C++) | 133 classes, 0.4 s | `Env` abstract factory of files, `EnvWrapper` decorator, pluggable `Comparator` / `FilterPolicy` / `Env` strategies, the `Iterator` family (7 concrete iterators) with its aggregates |
| [tcllib](https://github.com/tcltk/tcllib) TclOO modules | 95 classes, 0.6 s | all 75 superclass links resolved, `practcl` classes defined with `clay::define`, template methods in `math::exact` |

## Command line

```
archlens SOURCE [-o OUT] [-t TITLE] [-x GLOB ...] [-l LANG ...] [--min-confidence X] [--json] [--no-export] [--open] [-q]
```

* `SOURCE` — a package directory (with `__init__.py`), a source tree (e.g. `src/`) or a single file.
* `-l/--language` — `python`, `cpp` or `tcl` (repeatable); by default every language found is analysed.
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
├── analyzer.py   Python front-end (AST → classes, attributes, methods, behavioural facts) and analyze()
├── languages/    cpp.py (tree-sitter) and tcl.py (Tcl parser + TclOO), shared helpers
├── relations.py  language-neutral relation building and C++/Tcl scoped name lookup
├── patterns.py   pattern catalogue (names, categories, colours) and the detectors
├── render.py     model → JSON + page shells, metrics (DIT, NOC, fan-in/out)
├── cli.py
└── static/       archlens.js (layered layout, SVG diagrams, pages) and archlens.css
```

Front-ends fill a language-neutral model (`model.py`): classes, members, and behavioural facts about method
bodies (calls on `self`/members, iteration, `return self`, members written outside constructors, classes
instantiated, run-time class lookups). The detectors only read those facts, so a new language only needs a
front-end.

## Development

```bash
pip install -e '.[dev]'
pytest
archlens examples/patterns_zoo -o /tmp/zoo-report
```

## Limitations

* Static analysis only: attributes created dynamically (`setattr`, `__dict__` updates), Tcl classes created
  under computed names (`oo::class create ${ns}::cls`) and types only known at run time are not seen. Type
  hints (Python) greatly improve results; Tcl member types are inferred and marked as such by name/usage.
* C++ is parsed without a preprocessor: code hidden behind macros that change syntax beyond the common
  export/visibility macros may be partially read. Templates are shown as their generic definition.
* Only classes are diagrammed; module-level functions are counted but not drawn.
* Pattern detection is a review aid, not a proof — treat low-confidence matches as hints.
