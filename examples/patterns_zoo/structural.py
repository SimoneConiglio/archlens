"""Structural patterns: Adapter, Decorator, Proxy, Facade."""

from __future__ import annotations

from abc import ABC, abstractmethod


class DataSource(ABC):
    @abstractmethod
    def read(self) -> bytes: ...

    @abstractmethod
    def write(self, data: bytes) -> None: ...


class FileDataSource(DataSource):
    def __init__(self, path: str) -> None:
        self.path = path

    def read(self) -> bytes:
        with open(self.path, "rb") as fh:
            return fh.read()

    def write(self, data: bytes) -> None:
        with open(self.path, "wb") as fh:
            fh.write(data)


class CompressionDecorator(DataSource):
    def __init__(self, wrapped: DataSource) -> None:
        self._wrapped = wrapped

    def read(self) -> bytes:
        return self._wrapped.read()

    def write(self, data: bytes) -> None:
        self._wrapped.write(data)


class LegacyStorage:
    def fetch_blob(self, key: str) -> bytes:
        return b""

    def put_blob(self, key: str, blob: bytes) -> None:
        pass


class LegacyStorageAdapter(DataSource):
    def __init__(self, storage: LegacyStorage, key: str) -> None:
        self._storage = storage
        self._key = key

    def read(self) -> bytes:
        return self._storage.fetch_blob(self._key)

    def write(self, data: bytes) -> None:
        self._storage.put_blob(self._key, data)


class LazyDataSource(DataSource):
    """Virtual proxy: creates the real source on first use."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._real: FileDataSource | None = None

    def _load(self) -> FileDataSource:
        if self._real is None:
            self._real = FileDataSource(self._path)
        return self._real

    def read(self) -> bytes:
        return self._load().read()

    def write(self, data: bytes) -> None:
        self._load().write(data)


class Inventory:
    def reserve(self, sku: str) -> bool:
        return True


class Payments:
    def charge(self, amount: float) -> str:
        return "ok"


class Shipping:
    def ship(self, sku: str) -> str:
        return "tracking"


class OrderFacade:
    def __init__(self) -> None:
        self.inventory = Inventory()
        self.payments = Payments()
        self.shipping = Shipping()

    def place_order(self, sku: str, amount: float) -> str:
        self.inventory.reserve(sku)
        self.payments.charge(amount)
        return self.shipping.ship(sku)
