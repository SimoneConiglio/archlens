"""A small package that deliberately implements many classic design patterns.

It is used as the demo input for ArchLens and as the test fixture.
"""

from .creational import AppConfig, ShapeFactory, QueryBuilder
from .shapes import Circle, Shape, Square

__all__ = ["AppConfig", "ShapeFactory", "QueryBuilder", "Circle", "Shape", "Square"]
