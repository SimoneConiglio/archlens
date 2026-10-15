"""ArchLens: static architecture review for Python packages.

Point it at a package and it produces interactive HTML class diagrams with all
attributes, inheritance/composition/aggregation/dependency relations, and
colour-coded design patterns.
"""

__version__ = "0.1.0"

from .analyzer import analyze  # noqa: E402
from .render import render_site  # noqa: E402

__all__ = ["analyze", "render_site", "__version__"]
