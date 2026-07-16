"""MongoDB-backed storage for LLM generation records."""

from __future__ import annotations

import os
from copy import deepcopy
from typing import Any, Protocol
from urllib.parse import quote_plus

from pymongo import ASCENDING, MongoClient
from pymongo.collection import Collection


class MongoConfigurationError(RuntimeError):
    """Raised when MongoDB has not been configured or cannot be reached."""


class GenerationStore(Protocol):
    def ensure_ready(self) -> None: ...

    def add(self, record: dict[str, Any]) -> None: ...

    def by_id(self, record_id: str) -> dict[str, Any] | None: ...

    def by_selection(self, selection_id: str) -> list[dict[str, Any]]: ...

    def by_node(self, node_id: str) -> list[dict[str, Any]]: ...

    def by_logical_node(self, logical_node_id: str) -> list[dict[str, Any]]: ...


class MongoGenerationStore:
    """Persistent generation store with indexes for retrieval endpoints."""

    def __init__(self, uri: str, database_name: str, collection_name: str = "generations") -> None:
        self._client = MongoClient(uri, serverSelectionTimeoutMS=5_000)
        self._collection: Collection = self._client[database_name][collection_name]
        self._indexes_ready = False

    @classmethod
    def from_environment(cls) -> "MongoGenerationStore":
        uri = os.getenv("MONGODB_URI")
        if not uri:
            username = os.getenv("MONGODB_USERNAME")
            password = os.getenv("MONGODB_PASSWORD")
            host = os.getenv("MONGODB_HOST")
            if not username or not password or not host:
                raise MongoConfigurationError(
                    "Set MONGODB_URI, or set MONGODB_USERNAME, MONGODB_PASSWORD, and MONGODB_HOST."
                )
            uri = f"mongodb+srv://{quote_plus(username)}:{quote_plus(password)}@{host}/?retryWrites=true&w=majority"
        return cls(
            uri,
            os.getenv("MONGODB_DATABASE", "ct200"),
            os.getenv("MONGODB_COLLECTION", "generations"),
        )

    def _ensure_indexes(self) -> None:
        if self._indexes_ready:
            return
        self._collection.create_index([("id", ASCENDING)], unique=True, name="generation_id")
        self._collection.create_index([("selection_id", ASCENDING)], name="selection_id")
        self._collection.create_index([("node_snapshots.node_id", ASCENDING)], name="source_node_id")
        self._collection.create_index(
            [("node_snapshots.logical_node_id", ASCENDING)], name="source_logical_node_id"
        )
        self._indexes_ready = True

    def ensure_ready(self) -> None:
        try:
            self._client.admin.command("ping")
            self._ensure_indexes()
        except Exception as exc:
            raise MongoConfigurationError(f"Could not connect to MongoDB: {exc}") from exc

    @staticmethod
    def _without_object_id(record: dict[str, Any] | None) -> dict[str, Any] | None:
        if record is None:
            return None
        record.pop("_id", None)
        return record

    def add(self, record: dict[str, Any]) -> None:
        self._ensure_indexes()
        self._collection.insert_one(deepcopy(record))

    def by_id(self, record_id: str) -> dict[str, Any] | None:
        self._ensure_indexes()
        return self._without_object_id(self._collection.find_one({"id": record_id}))

    def by_selection(self, selection_id: str) -> list[dict[str, Any]]:
        self._ensure_indexes()
        return [
            self._without_object_id(record)
            for record in self._collection.find({"selection_id": selection_id}).sort("created_at", ASCENDING)
        ]

    def by_node(self, node_id: str) -> list[dict[str, Any]]:
        self._ensure_indexes()
        return [
            self._without_object_id(record)
            for record in self._collection.find({"node_snapshots.node_id": node_id}).sort("created_at", ASCENDING)
        ]

    def by_logical_node(self, logical_node_id: str) -> list[dict[str, Any]]:
        self._ensure_indexes()
        return [
            self._without_object_id(record)
            for record in self._collection.find({"node_snapshots.logical_node_id": logical_node_id}).sort("created_at", ASCENDING)
        ]


class UnconfiguredMongoGenerationStore:
    """Lets the API import, but fails clearly at startup until Mongo is configured."""

    def __init__(self, error: MongoConfigurationError) -> None:
        self._error = error

    def ensure_ready(self) -> None:
        raise self._error

    def add(self, record: dict[str, Any]) -> None:
        raise self._error

    def by_id(self, record_id: str) -> dict[str, Any] | None:
        raise self._error

    def by_selection(self, selection_id: str) -> list[dict[str, Any]]:
        raise self._error

    def by_node(self, node_id: str) -> list[dict[str, Any]]:
        raise self._error

    def by_logical_node(self, logical_node_id: str) -> list[dict[str, Any]]:
        raise self._error


class InMemoryGenerationStore:
    """Non-persistent store used only by automated tests and the demo script."""

    def __init__(self) -> None:
        self._records: list[dict[str, Any]] = []

    def ensure_ready(self) -> None:
        return None

    def add(self, record: dict[str, Any]) -> None:
        self._records.append(deepcopy(record))

    def by_id(self, record_id: str) -> dict[str, Any] | None:
        return next((deepcopy(record) for record in self._records if record["id"] == record_id), None)

    def by_selection(self, selection_id: str) -> list[dict[str, Any]]:
        return [deepcopy(record) for record in self._records if record["selection_id"] == selection_id]

    def by_node(self, node_id: str) -> list[dict[str, Any]]:
        return [
            deepcopy(record)
            for record in self._records
            if any(item["node_id"] == node_id for item in record["node_snapshots"])
        ]

    def by_logical_node(self, logical_node_id: str) -> list[dict[str, Any]]:
        return [
            deepcopy(record)
            for record in self._records
            if any(item["logical_node_id"] == logical_node_id for item in record["node_snapshots"])
        ]
