"""Small JSON document store for generation records.

The records are independent documents with nested test-case payloads and are
queried only by record/selection/node IDs. SQLite already owns the relational
tree; a local JSON store avoids adding an always-on MongoDB service to this
single-user assignment while keeping generated output physically separate.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Lock
from typing import Any


class JsonGenerationStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = Lock()

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8") as stream:
            return json.load(stream)

    def _write(self, records: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(records, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, self.path)

    def add(self, record: dict[str, Any]) -> None:
        with self._lock:
            records = self._read()
            records.append(record)
            self._write(records)

    def by_id(self, record_id: str) -> dict[str, Any] | None:
        with self._lock:
            return next((record for record in self._read() if record["id"] == record_id), None)

    def by_selection(self, selection_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [record for record in self._read() if record["selection_id"] == selection_id]

    def by_node(self, node_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [
                record
                for record in self._read()
                if any(item["node_id"] == node_id for item in record["node_snapshots"])
            ]
