from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from sqlalchemy import or_, select

from app.db import make_session_factory
from app.generation_store import JsonGenerationStore
from app.ingestion import ingest_pdf
from app.llm import OpenAICompatibleClient
from app.models import Node, Selection
from app.schemas import (
    ChangeResponse,
    CreateSelectionRequest,
    GenerateRequest,
    GenerationResponse,
    IngestRequest,
    IngestResponse,
    NodeDetail,
    NodeSummary,
    SelectionResponse,
)
from app.services import (
    create_selection,
    diff_for_node,
    generate,
    generation_response,
    latest_version,
    node_summary,
    selection_response,
    version_for,
)


def create_app(database_url: str = "sqlite:///./ct200.db", output_path: str = "generated_output.json", llm_client=None) -> FastAPI:
    app = FastAPI(title="CT-200 Document Intelligence API", version="1.0.0")
    app.state.Session = make_session_factory(database_url)
    app.state.store = JsonGenerationStore(output_path)
    app.state.llm_client = llm_client or OpenAICompatibleClient()

    @app.post("/documents/{document_name}/ingest", response_model=IngestResponse)
    def ingest(document_name: str, request: IngestRequest):
        source = Path(request.source_path)
        if not source.is_file():
            raise HTTPException(422, f"Source PDF does not exist: {source}")
        with app.state.Session() as session:
            version = ingest_pdf(session, document_name, source)
            return IngestResponse(document_name=document_name, version_id=version.id, version_number=version.version_number)

    @app.get("/documents/{document_name}/sections", response_model=list[NodeSummary])
    def sections(document_name: str, version: int | None = None):
        with app.state.Session() as session:
            chosen = version_for(session, document_name, version)
            nodes = session.scalars(
                select(Node).where(Node.document_version_id == chosen.id, Node.parent_node_id.is_(None)).order_by(Node.position)
            ).all()
            return [node_summary(node) for node in nodes]

    @app.get("/nodes/search", response_model=list[NodeSummary])
    def search(document_name: str, query: str = Query(min_length=1), version: int | None = None):
        with app.state.Session() as session:
            chosen = version_for(session, document_name, version)
            pattern = f"%{query}%"
            nodes = session.scalars(
                select(Node)
                .where(
                    Node.document_version_id == chosen.id,
                    or_(Node.heading.ilike(pattern), Node.body_text.ilike(pattern)),
                )
                .order_by(Node.position)
            ).all()
            return [node_summary(node) for node in nodes]

    @app.get("/nodes/{node_id}", response_model=NodeDetail)
    def get_node(node_id: str):
        with app.state.Session() as session:
            node = session.get(Node, node_id)
            if node is None:
                raise HTTPException(404, "Node not found")
            children = session.scalars(select(Node).where(Node.parent_node_id == node.id).order_by(Node.position)).all()
            return {
                **node_summary(node),
                "version_id": node.document_version_id,
                "parent_node_id": node.parent_node_id,
                "body_text": node.body_text,
                "blocks": node.blocks,
                "children": [node_summary(child) for child in children],
            }

    @app.get("/nodes/{node_id}/changes", response_model=ChangeResponse)
    def changes(node_id: str):
        with app.state.Session() as session:
            node = session.get(Node, node_id)
            if node is None:
                raise HTTPException(404, "Node not found")
            return diff_for_node(session, node)

    @app.post("/selections", response_model=SelectionResponse, status_code=201)
    def add_selection(request: CreateSelectionRequest):
        with app.state.Session() as session:
            selection = create_selection(session, request.name, request.node_ids)
            return selection_response(selection)

    @app.get("/selections/{selection_id}", response_model=SelectionResponse)
    def get_selection(selection_id: str):
        with app.state.Session() as session:
            selection = session.get(Selection, selection_id)
            if selection is None:
                raise HTTPException(404, "Selection not found")
            return selection_response(selection)

    @app.post("/selections/{selection_id}/generations", response_model=GenerationResponse)
    def create_generation(selection_id: str, request: GenerateRequest):
        with app.state.Session() as session:
            selection = session.get(Selection, selection_id)
            if selection is None:
                raise HTTPException(404, "Selection not found")
            return generate(session, app.state.store, app.state.llm_client, selection, request.force_regenerate)

    @app.get("/generations", response_model=list[GenerationResponse])
    def get_generations(selection_id: str | None = None, node_id: str | None = None):
        if (selection_id is None) == (node_id is None):
            raise HTTPException(422, "Supply exactly one of selection_id or node_id")
        with app.state.Session() as session:
            if selection_id:
                records = app.state.store.by_selection(selection_id)
            else:
                node = session.get(Node, node_id)
                if node is None:
                    raise HTTPException(404, "Node not found")
                # A current-version snapshot resolves records generated from
                # older snapshots of the same logical requirement.
                records = app.state.store.by_logical_node(node.logical_node_id)
            return [generation_response(session, record) for record in records]

    return app


app = create_app()
