from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class IngestRequest(BaseModel):
    source_path: str


class IngestResponse(BaseModel):
    document_name: str
    version_id: str
    version_number: int


class NodeSummary(BaseModel):
    id: str
    logical_node_id: str
    number: str
    heading: str
    nominal_level: int
    depth: int
    numbering_gap: bool
    content_hash: str


class NodeDetail(NodeSummary):
    version_id: str
    parent_node_id: str | None
    body_text: str
    blocks: list[dict]
    children: list[NodeSummary]


class ChangeResponse(BaseModel):
    node_id: str
    logical_node_id: str
    changed: bool
    versions: list[int]
    diff_summary: str | None


class CreateSelectionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    node_ids: list[str] = Field(min_length=1)


class SelectionItemResponse(BaseModel):
    node_id: str
    version_id: str
    logical_node_id: str
    heading: str
    content_hash: str


class SelectionResponse(BaseModel):
    id: str
    name: str
    items: list[SelectionItemResponse]


class GenerateRequest(BaseModel):
    force_regenerate: bool = False


class TestCaseIdea(BaseModel):
    title: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    preconditions: list[str] = Field(min_length=1)
    steps: list[str] = Field(min_length=1)
    expected_result: str = Field(min_length=1)
    source_node_ids: list[str] = Field(min_length=1)


class GenerationPayload(BaseModel):
    test_cases: list[TestCaseIdea] = Field(min_length=3, max_length=5)


class GenerationResponse(BaseModel):
    id: str
    selection_id: str
    status: Literal["completed", "generation_failed"]
    test_cases: list[TestCaseIdea] | None
    raw_responses: list[str | None]
    error: str | None
    stale: bool
    stale_reasons: list[str]
    idempotent: bool = False
