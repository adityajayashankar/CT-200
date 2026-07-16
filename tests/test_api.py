import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.generation_store import InMemoryGenerationStore
from app.main import create_app


V1 = Path("data/ct200_manual.pdf").resolve()
V2 = Path("data/ct200_manual_v2.pdf").resolve()


class ValidLLM:
    def __init__(self):
        self.calls = 0

    def complete(self, prompt: str) -> str:
        self.calls += 1
        node_id = re.search(r"NODE_ID: ([^\n]+)", prompt).group(1)
        return json.dumps(
            {
                "test_cases": [
                    {
                        "title": f"Case {index}",
                        "rationale": "Checks a stated device behavior.",
                        "preconditions": ["Device is powered on."],
                        "steps": ["Perform the documented action."],
                        "expected_result": "The documented behavior occurs.",
                        "source_node_ids": [node_id],
                    }
                    for index in range(1, 4)
                ]
            }
        )


class BrokenLLM:
    def __init__(self):
        self.calls = 0

    def complete(self, prompt: str) -> str:
        self.calls += 1
        return "not JSON" if self.calls == 1 else '{"test_cases": []}'


def make_client(tmp_path, llm):
    return TestClient(
        create_app(
            f"sqlite:///{tmp_path / 'test.db'}",
            llm_client=llm,
            generation_store=InMemoryGenerationStore(),
        )
    )


def test_browse_selection_generation_and_staleness_flow(tmp_path):
    llm = ValidLLM()
    client = make_client(tmp_path, llm)

    assert client.post("/documents/ct200/ingest", json={"source_path": str(V1)}).json()["version_number"] == 1
    sections = client.get("/documents/ct200/sections").json()
    assert [section["number"] for section in sections] == [str(i) for i in range(1, 9)]
    found = client.get("/nodes/search", params={"document_name": "ct200", "query": "Cuff Inflation"}).json()
    cuff = next(node for node in found if node["number"] == "3.2")
    detail = client.get(f"/nodes/{cuff['id']}").json()
    assert "40 mmHg increments" in detail["body_text"]

    selection = client.post("/selections", json={"name": "Inflation safety", "node_ids": [cuff["id"]]}).json()
    assert selection["items"][0]["node_id"] == cuff["id"]
    first = client.post(f"/selections/{selection['id']}/generations", json={}).json()
    assert first["status"] == "completed"
    assert len(first["test_cases"]) == 3
    duplicate = client.post(f"/selections/{selection['id']}/generations", json={}).json()
    assert duplicate["id"] == first["id"]
    assert duplicate["idempotent"] is True
    assert llm.calls == 1

    assert client.post("/documents/ct200/ingest", json={"source_path": str(V2)}).json()["version_number"] == 2
    change = client.get(f"/nodes/{cuff['id']}/changes").json()
    assert change["changed"] is True
    assert "40 mmHg" in change["diff_summary"]
    generated = client.get("/generations", params={"selection_id": selection["id"]}).json()
    assert generated[0]["stale"] is True
    assert "3.2 Cuff Inflation Sequence content changed" in generated[0]["stale_reasons"]
    v2_cuff = next(
        node
        for node in client.get("/nodes/search", params={"document_name": "ct200", "query": "Cuff Inflation"}).json()
        if node["number"] == "3.2"
    )
    assert client.get("/generations", params={"node_id": v2_cuff["id"]}).json()[0]["id"] == first["id"]
    assert client.get(f"/selections/{selection['id']}").json()["items"][0]["version_id"] == selection["items"][0]["version_id"]


def test_generation_retries_once_then_persists_validation_failure(tmp_path):
    llm = BrokenLLM()
    client = make_client(tmp_path, llm)
    client.post("/documents/ct200/ingest", json={"source_path": str(V1)})
    node = client.get("/nodes/search", params={"document_name": "ct200", "query": "Overpressure Protection"}).json()[0]
    selection = client.post("/selections", json={"name": "overpressure", "node_ids": [node["id"]]}).json()

    response = client.post(f"/selections/{selection['id']}/generations", json={}).json()
    assert response["status"] == "generation_failed"
    assert response["test_cases"] is None
    assert len(response["raw_responses"]) == 2
    assert llm.calls == 2
