"""Creational patterns: Singleton, Factory, Abstract Factory, Builder."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .shapes import Circle, Shape, Square


class AppConfig:
    """Process-wide configuration (Singleton)."""

    _instance: "AppConfig | None" = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        self.debug = False
        self.values: dict[str, str] = {}


class SingletonMeta(type):
    _instances: dict = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]


class Logger(metaclass=SingletonMeta):
    def __init__(self) -> None:
        self.lines: list[str] = []

    def log(self, msg: str) -> None:
        self.lines.append(msg)


class ShapeFactory:
    def create(self, kind: str, size: float) -> Shape:
        if kind == "circle":
            return Circle(size)
        return Square(size)


class Button(ABC):
    @abstractmethod
    def render(self) -> str: ...


class Checkbox(ABC):
    @abstractmethod
    def toggle(self) -> None: ...


class DarkButton(Button):
    def render(self) -> str:
        return "<dark button>"


class DarkCheckbox(Checkbox):
    def toggle(self) -> None:
        pass


class WidgetFactory(ABC):
    @abstractmethod
    def create_button(self) -> Button: ...

    @abstractmethod
    def create_checkbox(self) -> Checkbox: ...


class DarkWidgetFactory(WidgetFactory):
    def create_button(self) -> Button:
        return DarkButton()

    def create_checkbox(self) -> Checkbox:
        return DarkCheckbox()


class Query:
    def __init__(self, table: str, fields: list[str], where: list[str], limit: int | None) -> None:
        self.table = table
        self.fields = fields
        self.where = where
        self.limit = limit


class QueryBuilder:
    def __init__(self, table: str) -> None:
        self._table = table
        self._fields: list[str] = []
        self._where: list[str] = []
        self._limit: int | None = None

    def select(self, *fields: str) -> "QueryBuilder":
        self._fields.extend(fields)
        return self

    def where(self, clause: str) -> "QueryBuilder":
        self._where.append(clause)
        return self

    def limit(self, n: int) -> "QueryBuilder":
        self._limit = n
        return self

    def build(self) -> Query:
        return Query(self._table, self._fields, self._where, self._limit)
