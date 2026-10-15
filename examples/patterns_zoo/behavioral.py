"""Behavioral patterns: Observer, Strategy, State, Template Method, Command, Chain."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol


class Observer(Protocol):
    def update(self, event: str) -> None: ...


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[Observer] = []

    def subscribe(self, observer: Observer) -> None:
        self._subscribers.append(observer)

    def notify(self, event: str) -> None:
        for sub in self._subscribers:
            sub.update(event)


class AuditLog:
    def update(self, event: str) -> None:
        print(event)


class SortStrategy(ABC):
    @abstractmethod
    def sort(self, data: list[int]) -> list[int]: ...


class QuickSort(SortStrategy):
    def sort(self, data: list[int]) -> list[int]:
        return sorted(data)


class BubbleSort(SortStrategy):
    def sort(self, data: list[int]) -> list[int]:
        return sorted(data)


class Sorter:
    def __init__(self, strategy: SortStrategy) -> None:
        self.strategy = strategy

    def run(self, data: list[int]) -> list[int]:
        return self.strategy.sort(data)


class TrafficState(ABC):
    @abstractmethod
    def next(self, light: "TrafficLight") -> None: ...


class Green(TrafficState):
    def next(self, light: "TrafficLight") -> None:
        light.state = Red()


class Red(TrafficState):
    def next(self, light: "TrafficLight") -> None:
        light.state = Green()


class TrafficLight:
    def __init__(self) -> None:
        self.state: TrafficState = Red()

    def change(self) -> None:
        self.state.next(self)


class Report(ABC):
    def generate(self) -> str:
        header = self.header()
        body = self.body()
        return header + body

    @abstractmethod
    def header(self) -> str: ...

    @abstractmethod
    def body(self) -> str: ...


class SalesReport(Report):
    def header(self) -> str:
        return "Sales\n"

    def body(self) -> str:
        return "..."


class Command(ABC):
    @abstractmethod
    def execute(self) -> None: ...

    def undo(self) -> None:
        pass


class CopyCommand(Command):
    def execute(self) -> None:
        pass


class PasteCommand(Command):
    def execute(self) -> None:
        pass


class CommandHistory:
    def __init__(self) -> None:
        self.history: list[Command] = []

    def run(self, cmd: Command) -> None:
        cmd.execute()
        self.history.append(cmd)

    def undo_all(self) -> None:
        for cmd in self.history:
            cmd.undo()


class Handler(ABC):
    def __init__(self, successor: "Handler | None" = None) -> None:
        self._next = successor

    def handle(self, request: str) -> str | None:
        if self._next is not None:
            return self._next.handle(request)
        return None


class AuthHandler(Handler):
    def handle(self, request: str) -> str | None:
        if request == "auth":
            return "authenticated"
        return super().handle(request)


class PluginRegistry:
    _plugins: dict[str, type] = {}

    @classmethod
    def register(cls, name: str):
        def deco(klass: type) -> type:
            cls._plugins[name] = klass
            return klass

        return deco


class Transaction:
    def __enter__(self) -> "Transaction":
        return self

    def __exit__(self, *exc) -> None:
        pass
