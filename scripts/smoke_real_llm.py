"""Optional live-provider smoke test; it spends one real LLM request.

Set LLM_API_KEY and LLM_MODEL first. LLM_BASE_URL defaults to Groq's
OpenAI-compatible endpoint but can be pointed at another compatible provider.
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from app.generation_store import MongoGenerationStore
from app.main import create_app


def main() -> None:
    if not os.getenv("LLM_API_KEY") or not os.getenv("LLM_MODEL"):
        raise SystemExit("Set LLM_API_KEY and LLM_MODEL before running this live-provider smoke test.")

    with tempfile.TemporaryDirectory() as temporary:
        app = create_app(
            f"sqlite:///{Path(temporary) / 'smoke.db'}",
            generation_store=MongoGenerationStore.from_environment(),
        )
        client = TestClient(app)
        client.post("/documents/ct200/ingest", json={"source_path": str(ROOT / "data/ct200_manual.pdf")}).raise_for_status()
        node = next(
            item
            for item in client.get("/nodes/search", params={"document_name": "ct200", "query": "Overpressure Protection"}).json()
            if item["number"] == "4.1"
        )
        selection = client.post("/selections", json={"name": "live smoke", "node_ids": [node["id"]]}).json()
        response = client.post(f"/selections/{selection['id']}/generations", json={})
        response.raise_for_status()
        result = response.json()
        print("Generation status:", result["status"])
        print("Generated test cases:", len(result["test_cases"] or []))
        if result["status"] != "completed":
            print("Failure detail:", result["error"])
            raise SystemExit(1)
        app.state.Session.kw["bind"].dispose()


if __name__ == "__main__":
    main()
