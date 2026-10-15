"""Shape hierarchy: Composite, Prototype, Visitor elements."""

from __future__ import annotations

import copy
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Point:
    x: float = 0.0
    y: float = 0.0


@dataclass
class Style:
    stroke: str = "black"
    fill: str | None = None
    width: float = 1.0


class Shape(ABC):
    """Component of the shape tree."""

    def __init__(self, origin: Point | None = None) -> None:
        self.origin = origin or Point()
        self.style = Style()

    @abstractmethod
    def area(self) -> float: ...

    @abstractmethod
    def accept(self, visitor: "ShapeVisitor"): ...

    def clone(self) -> "Shape":
        return copy.deepcopy(self)


class Circle(Shape):
    def __init__(self, radius: float, origin: Point | None = None) -> None:
        super().__init__(origin)
        self.radius = radius

    def area(self) -> float:
        return 3.14159 * self.radius**2

    def accept(self, visitor):
        return visitor.visit_circle(self)


class Square(Shape):
    def __init__(self, side: float, origin: Point | None = None) -> None:
        super().__init__(origin)
        self.side = side

    def area(self) -> float:
        return self.side**2

    def accept(self, visitor):
        return visitor.visit_square(self)


class Group(Shape):
    """Composite: a shape made of shapes."""

    def __init__(self) -> None:
        super().__init__()
        self.children: list[Shape] = []

    def add(self, shape: Shape) -> "Group":
        self.children.append(shape)
        return self

    def area(self) -> float:
        return sum(child.area() for child in self.children)

    def accept(self, visitor):
        return visitor.visit_group(self)


class ShapeVisitor:
    def visit_circle(self, circle: Circle): ...

    def visit_square(self, square: Square): ...

    def visit_group(self, group: Group):
        for child in group.children:
            child.accept(self)


class AreaVisitor(ShapeVisitor):
    def __init__(self) -> None:
        self.total = 0.0

    def visit_circle(self, circle: Circle):
        self.total += circle.area()

    def visit_square(self, square: Square):
        self.total += square.area()


class ShapeIterator:
    def __init__(self, group: Group) -> None:
        self._stack = list(group.children)

    def __iter__(self):
        return self

    def __next__(self) -> Shape:
        if not self._stack:
            raise StopIteration
        return self._stack.pop()


@dataclass
class Drawing:
    title: str
    root: Group = field(default_factory=Group)
    tags: list[str] = field(default_factory=list)
