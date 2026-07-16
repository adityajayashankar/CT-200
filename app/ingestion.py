from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.matching import IncomingNode, PriorNode, match_nodes
from app.models import Document, DocumentVersion, LogicalNode, Node
from app.parser import ContentBlock, ParsedNode, parse_ct200_pdf


def normalized_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _serialize_blocks(blocks: list[ContentBlock]) -> list[dict]:
    return [{"block_type": block.block_type, "text": block.text, "cells": block.cells} for block in blocks]


def _latest_version(session: Session, document_id: str) -> DocumentVersion | None:
    return session.scalar(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == document_id)
        .order_by(DocumentVersion.version_number.desc())
    )


def ingest_pdf(session: Session, document_name: str, source_path: str | Path) -> DocumentVersion:
    """Persist a new immutable snapshot, retaining logical identity where safe."""
    source = Path(source_path)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    document = session.scalar(select(Document).where(Document.name == document_name))
    if document is None:
        document = Document(name=document_name)
        session.add(document)
        session.flush()
    latest = _latest_version(session, document.id)
    if latest and latest.source_hash == source_hash:
        return latest

    version = DocumentVersion(
        document_id=document.id,
        version_number=(latest.version_number + 1) if latest else 1,
        source_path=str(source),
        source_hash=source_hash,
    )
    session.add(version)
    session.flush()

    prior: list[PriorNode] = []
    if latest:
        prior_nodes = session.scalars(select(Node).where(Node.document_version_id == latest.id)).all()
        by_snapshot_id = {node.id: node for node in prior_nodes}
        prior = [
            PriorNode(
                logical_id=node.logical_node_id,
                parent_logical_id=by_snapshot_id[node.parent_node_id].logical_node_id if node.parent_node_id else None,
                heading=node.heading,
            )
            for node in prior_nodes
        ]

    parsed = parse_ct200_pdf(source)
    flattened = parsed.flatten()
    matches = match_nodes(
        prior,
        [IncomingNode(node.uid, node.parent_uid, node.heading) for node in flattened],
    )
    snapshots: dict[str, Node] = {}
    for position, parsed_node in enumerate(flattened):
        matched = matches[parsed_node.uid]
        logical_id = matched.logical_id
        if logical_id is None:
            logical = LogicalNode(document_id=document.id)
            session.add(logical)
            session.flush()
            logical_id = logical.id
        snapshot = Node(
            document_version_id=version.id,
            logical_node_id=logical_id,
            parent_node_id=snapshots[parsed_node.parent_uid].id if parsed_node.parent_uid else None,
            source_uid=parsed_node.uid,
            number=parsed_node.number,
            heading=parsed_node.heading,
            nominal_level=parsed_node.nominal_level,
            depth=parsed_node.depth,
            numbering_gap=parsed_node.numbering_gap,
            position=position,
            body_text=parsed_node.body_text,
            content_hash=normalized_hash(parsed_node.body_text),
            blocks=_serialize_blocks(parsed_node.blocks),
        )
        session.add(snapshot)
        session.flush()
        snapshots[parsed_node.uid] = snapshot
    session.commit()
    return version
