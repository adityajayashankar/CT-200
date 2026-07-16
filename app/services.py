from __future__ import annotations

import difflib
import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.generation_store import JsonGenerationStore
from app.llm import LLMClient
from app.models import Document, DocumentVersion, Node, Selection, SelectionItem
from app.schemas import GenerationPayload, GenerationResponse, TestCaseIdea


def node_summary(node: Node) -> dict:
    return {
        "id": node.id,
        "logical_node_id": node.logical_node_id,
        "number": node.number,
        "heading": node.heading,
        "nominal_level": node.nominal_level,
        "depth": node.depth,
        "numbering_gap": node.numbering_gap,
        "content_hash": node.content_hash,
    }


def latest_version(session: Session, document_name: str) -> DocumentVersion:
    document = session.scalar(select(Document).where(Document.name == document_name))
    if document is None:
        raise HTTPException(404, f"Document '{document_name}' was not found")
    version = session.scalar(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == document.id)
        .order_by(DocumentVersion.version_number.desc())
    )
    if version is None:
        raise HTTPException(404, f"Document '{document_name}' has no ingested versions")
    return version


def version_for(session: Session, document_name: str, version_number: int | None) -> DocumentVersion:
    if version_number is None:
        return latest_version(session, document_name)
    document = session.scalar(select(Document).where(Document.name == document_name))
    if document is None:
        raise HTTPException(404, f"Document '{document_name}' was not found")
    version = session.scalar(
        select(DocumentVersion).where(
            DocumentVersion.document_id == document.id,
            DocumentVersion.version_number == version_number,
        )
    )
    if version is None:
        raise HTTPException(404, f"Version {version_number} was not found")
    return version


def staleness(session: Session, node_snapshots: list[dict]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    for saved in node_snapshots:
        latest = session.scalar(
            select(Node)
            .join(DocumentVersion)
            .where(
                Node.logical_node_id == saved["logical_node_id"],
                DocumentVersion.document_id == saved["document_id"],
            )
            .order_by(DocumentVersion.version_number.desc())
        )
        if latest is None:
            reasons.append(f"Logical node {saved['logical_node_id']} is absent from the latest version")
        elif latest.content_hash != saved["content_hash"]:
            reasons.append(f"{latest.number} {latest.heading} content changed")
    return bool(reasons), reasons


def selection_response(selection: Selection) -> dict:
    return {
        "id": selection.id,
        "name": selection.name,
        "items": [
            {
                "node_id": item.node.id,
                "version_id": item.node.document_version_id,
                "logical_node_id": item.node.logical_node_id,
                "heading": item.node.heading,
                "content_hash": item.node.content_hash,
            }
            for item in selection.items
        ],
    }


def create_selection(session: Session, name: str, node_ids: list[str]) -> Selection:
    if len(node_ids) != len(set(node_ids)):
        raise HTTPException(422, "A selection cannot contain the same snapshot node twice")
    nodes = session.scalars(select(Node).where(Node.id.in_(node_ids))).all()
    if len(nodes) != len(node_ids):
        found = {node.id for node in nodes}
        raise HTTPException(404, f"Unknown node IDs: {sorted(set(node_ids) - found)}")
    by_id = {node.id: node for node in nodes}
    selection = Selection(name=name)
    session.add(selection)
    session.flush()
    for node_id in node_ids:
        session.add(SelectionItem(selection_id=selection.id, node_id=by_id[node_id].id))
    session.commit()
    session.refresh(selection)
    return selection


def _fingerprint(selection: Selection) -> tuple[str, list[dict]]:
    snapshots = [
        {
            "node_id": item.node.id,
            "logical_node_id": item.node.logical_node_id,
            "document_id": item.node.document_version.document_id,
            "content_hash": item.node.content_hash,
        }
        for item in selection.items
    ]
    snapshots.sort(key=lambda item: item["node_id"])
    canonical = json.dumps({"selection_id": selection.id, "nodes": snapshots}, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest(), snapshots


def _prompt(selection: Selection) -> str:
    parts = []
    for item in selection.items:
        node = item.node
        parts.append(f"NODE_ID: {node.id}\nSECTION: {node.number} {node.heading}\nTEXT:\n{node.body_text}")
    return """Generate exactly 3 to 5 concrete, executable QA test-case ideas based only on the selected CT-200 manual text.
Return one JSON object matching exactly this schema:
{"test_cases":[{"title":"...","rationale":"...","preconditions":["..."],"steps":["..."],"expected_result":"...","source_node_ids":["selected node UUID"]}]}
Each source_node_ids value must be one of the supplied NODE_ID values. Do not make clinical claims not supported by the text.

SELECTED SOURCE:\n""" + "\n\n".join(parts)


def _validate_generation(raw: str, selected_ids: set[str]) -> GenerationPayload:
    payload = GenerationPayload.model_validate_json(raw)
    for case in payload.test_cases:
        unknown = set(case.source_node_ids) - selected_ids
        if unknown:
            raise ValueError(f"test case cites node IDs outside the selection: {sorted(unknown)}")
    return payload


def generation_response(session: Session, record: dict, *, idempotent: bool = False) -> GenerationResponse:
    stale, reasons = staleness(session, record["node_snapshots"])
    cases = [TestCaseIdea.model_validate(case) for case in record["test_cases"]] if record["test_cases"] else None
    return GenerationResponse(
        id=record["id"],
        selection_id=record["selection_id"],
        status=record["status"],
        test_cases=cases,
        raw_responses=record["raw_responses"],
        error=record["error"],
        stale=stale,
        stale_reasons=reasons,
        idempotent=idempotent,
    )


def generate(
    session: Session,
    store: JsonGenerationStore,
    client: LLMClient,
    selection: Selection,
    force_regenerate: bool,
) -> GenerationResponse:
    fingerprint, snapshots = _fingerprint(selection)
    if not force_regenerate:
        existing = next((record for record in store.by_selection(selection.id) if record["fingerprint"] == fingerprint), None)
        if existing:
            return generation_response(session, existing, idempotent=True)

    raw_responses: list[str | None] = []
    error: str | None = None
    payload: GenerationPayload | None = None
    prompt = _prompt(selection)
    for attempt in range(2):
        try:
            raw = client.complete(prompt)
            raw_responses.append(raw)
            payload = _validate_generation(raw, {item.node.id for item in selection.items})
            break
        except (ValidationError, ValueError) as exc:
            error = str(exc)
            if attempt == 0:
                prompt += f"\n\nYour previous response failed validation: {error}. Return corrected JSON only."
        except Exception as exc:  # provider/network/configuration failure remains auditable
            raw_responses.append(None)
            error = f"LLM request failed: {exc}"
            break

    record = {
        "id": str(uuid4()),
        "selection_id": selection.id,
        "fingerprint": fingerprint,
        "status": "completed" if payload else "generation_failed",
        "test_cases": [case.model_dump() for case in payload.test_cases] if payload else None,
        "raw_responses": raw_responses,
        "error": error,
        "node_snapshots": snapshots,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    store.add(record)
    return generation_response(session, record)


def diff_for_node(session: Session, node: Node) -> dict:
    snapshots = session.scalars(
        select(Node)
        .join(DocumentVersion)
        .where(Node.logical_node_id == node.logical_node_id)
        .order_by(DocumentVersion.version_number)
    ).all()
    hashes = {snapshot.content_hash for snapshot in snapshots}
    diff = None
    if len(hashes) > 1:
        before, after = snapshots[-2], snapshots[-1]
        lines = list(
            difflib.unified_diff(
                before.body_text.splitlines(),
                after.body_text.splitlines(),
                fromfile=f"v{before.document_version.version_number}",
                tofile=f"v{after.document_version.version_number}",
                lineterm="",
            )
        )
        diff = "\n".join(lines[:20]) or "Content hash changed; no line-level summary available."
    return {
        "node_id": node.id,
        "logical_node_id": node.logical_node_id,
        "changed": len(hashes) > 1,
        "versions": [snapshot.document_version.version_number for snapshot in snapshots],
        "diff_summary": diff,
    }
