# CT-200 Document Intelligence System

A FastAPI backend that reconstructs the CT-200 manual as a versioned tree,
pins user selections to immutable node snapshots, generates structured QA
ideas, and flags those ideas as stale after a new document version changes
their source text.

There is intentionally no UI. The assignment explicitly scopes a frontend
out; FastAPI's interactive API is available at `/docs` when the server runs.

## Setup

Use Python 3.11+ (the project was tested with Python 3.13):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest -q
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs` to exercise the API.

## LLM configuration

Generation uses an OpenAI-compatible chat-completions endpoint. Groq,
OpenRouter, or another compatible provider can be used:

```powershell
$env:LLM_API_KEY = "your-provider-key"
$env:LLM_MODEL = "your-model-name"
$env:LLM_BASE_URL = "https://api.groq.com/openai/v1" # optional; this is the default
```

Without an API key/model, a generation request is recorded as
`generation_failed` with the configuration error preserved; it is not silently
replaced with invented test cases.

## v1 → v2 flow

Ingest v1, use the returned snapshot node IDs to create a selection and
generate test cases, then ingest v2. The saved generation becomes stale when
one of its pinned content hashes differs from the latest snapshot for the
same logical node.

```powershell
curl.exe -X POST http://127.0.0.1:8000/documents/ct200/ingest -H "Content-Type: application/json" -d '{"source_path":"data/ct200_manual.pdf"}'
curl.exe "http://127.0.0.1:8000/nodes/search?document_name=ct200&query=Cuff%20Inflation"
curl.exe -X POST http://127.0.0.1:8000/selections -H "Content-Type: application/json" -d '{"name":"Inflation safety","node_ids":["NODE_ID_FROM_SEARCH"]}'
curl.exe -X POST http://127.0.0.1:8000/selections/SELECTION_ID/generations -H "Content-Type: application/json" -d '{}'
curl.exe -X POST http://127.0.0.1:8000/documents/ct200/ingest -H "Content-Type: application/json" -d '{"source_path":"data/ct200_manual_v2.pdf"}'
curl.exe "http://127.0.0.1:8000/generations?selection_id=SELECTION_ID"
```

For a keyless, reproducible demonstration of the same API flow, run:

```powershell
python scripts/demo_flow.py
```

It injects a deterministic test LLM only for the demo; production requests
use the configured provider.

## Key endpoints

- `POST /documents/{document_name}/ingest` — ingest v1 or a later version.
- `GET /documents/{document_name}/sections?version=1` — root sections;
  version defaults to latest.
- `GET /nodes/{node_id}` and `GET /nodes/search` — browse/search snapshots.
- `GET /nodes/{node_id}/changes` — version history and lightweight text diff.
- `POST /selections`, `GET /selections/{id}` — version-pinned selections.
- `POST /selections/{id}/generations` — structured LLM generation; identical
  selected content is idempotent unless `force_regenerate` is true.
- `GET /generations?selection_id=...` or `?node_id=...` — generated cases
  with queryable `stale` and `stale_reasons` fields.

See [docs/approach.md](docs/approach.md) for decisions, limitations, and the
data model.
