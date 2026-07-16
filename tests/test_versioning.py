from pathlib import Path

from sqlalchemy import select

from app.db import make_session_factory
from app.ingestion import ingest_pdf
from app.matching import IncomingNode, PriorNode, match_nodes
from app.models import Node


V1 = Path("data/ct200_manual.pdf")
V2 = Path("data/ct200_manual_v2.pdf")


def test_reingestion_preserves_logical_ids_and_changed_hashes(tmp_path):
    Session = make_session_factory(f"sqlite:///{tmp_path / 'ct200.db'}")
    with Session() as session:
        first = ingest_pdf(session, "ct200", V1)
        assert first.document.title == "CardioTrack CT-200 Home Blood Pressure Monitor — Technical & User Manual"
        v1_nodes = session.scalars(select(Node).where(Node.document_version_id == first.id)).all()
        first_battery = next(node for node in v1_nodes if node.number == "2.1.1.1")

        second = ingest_pdf(session, "ct200", V2)
        v2_nodes = session.scalars(select(Node).where(Node.document_version_id == second.id)).all()
        second_battery = next(node for node in v2_nodes if node.number == "2.1.1.1")
        v2_export = next(node for node in v2_nodes if node.number == "5.3")

        assert second.version_number == 2
        assert first_battery.logical_node_id == second_battery.logical_node_id
        assert first_battery.content_hash != second_battery.content_hash
        assert v2_export.logical_node_id not in {node.logical_node_id for node in v1_nodes}


def test_matching_refuses_documented_ambiguous_duplicate_siblings():
    matches = match_nodes(
        [
            PriorNode("old-a", "parent", "Notes"),
            PriorNode("old-b", "parent", "Notes"),
        ],
        [
            IncomingNode("parent", None, "Section"),
            IncomingNode("child", "parent", "Notes"),
        ],
    )
    # The parent itself is deliberately unmatched; simulate its already-known
    # logical identity by making the incoming root use the same title below.
    root_matches = match_nodes(
        [PriorNode("parent", None, "Section"), *[
            PriorNode("old-a", "parent", "Notes"),
            PriorNode("old-b", "parent", "Notes"),
        ]],
        [IncomingNode("parent", None, "Section"), IncomingNode("child", "parent", "Notes")],
    )
    assert root_matches["child"].logical_id is None
    assert root_matches["child"].reason == "ambiguous duplicate sibling heading"
