"""Run the v1 → selection → generation → v2 → stale flow without an API key."""

import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from app.generation_store import InMemoryGenerationStore
from app.main import create_app


class DemoLLM:
    def complete(self, prompt: str) -> str:
        node_id = re.search(r"NODE_ID: ([^\n]+)", prompt).group(1)
        return json.dumps(
            {
                "test_cases": [
                    {
                        "title": f"Documented behavior check {n}",
                        "rationale": "Derived from the selected CT-200 text.",
                        "preconditions": ["Set up the device as specified."],
                        "steps": ["Perform the selected documented behavior."],
                        "expected_result": "The behavior matches the manual.",
                        "source_node_ids": [node_id],
                    }
                    for n in range(1, 4)
                ]
            }
        )


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        app = create_app(
            f"sqlite:///{Path(temporary) / 'demo.db'}",
            llm_client=DemoLLM(),
            generation_store=InMemoryGenerationStore(),
        )
        client = TestClient(app)
        print("Ingest v1:", client.post("/documents/ct200/ingest", json={"source_path": str(ROOT / "data/ct200_manual.pdf")}).json())
        inflation = next(
            node
            for node in client.get("/nodes/search", params={"document_name": "ct200", "query": "Cuff Inflation"}).json()
            if node["number"] == "3.2"
        )
        selection = client.post("/selections", json={"name": "Inflation safety", "node_ids": [inflation["id"]]}).json()
        generation = client.post(f"/selections/{selection['id']}/generations", json={}).json()
        print("Generation before v2 is stale:", generation["stale"])
        print("Ingest v2:", client.post("/documents/ct200/ingest", json={"source_path": str(ROOT / "data/ct200_manual_v2.pdf")}).json())
        retrieved = client.get("/generations", params={"selection_id": selection["id"]}).json()[0]
        print("Generation after v2 is stale:", retrieved["stale"])
        print("Reasons:", retrieved["stale_reasons"])
        # Windows keeps SQLite files locked until the engine is disposed.
        app.state.Session.kw["bind"].dispose()


if __name__ == "__main__":
    main()
