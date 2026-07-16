from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def new_id() -> str:
    return str(uuid4())


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    versions: Mapped[list["DocumentVersion"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    logical_nodes: Mapped[list["LogicalNode"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version_number", name="uq_document_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    source_path: Mapped[str] = mapped_column(Text)
    source_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    document: Mapped[Document] = relationship(back_populates="versions")
    nodes: Mapped[list["Node"]] = relationship(back_populates="document_version", cascade="all, delete-orphan")


class LogicalNode(Base):
    __tablename__ = "logical_nodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    document: Mapped[Document] = relationship(back_populates="logical_nodes")
    snapshots: Mapped[list["Node"]] = relationship(back_populates="logical_node")


class Node(Base):
    __tablename__ = "nodes"
    __table_args__ = (UniqueConstraint("document_version_id", "source_uid", name="uq_version_source_node"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id"), index=True)
    logical_node_id: Mapped[str] = mapped_column(ForeignKey("logical_nodes.id"), index=True)
    parent_node_id: Mapped[str | None] = mapped_column(ForeignKey("nodes.id"), nullable=True, index=True)
    source_uid: Mapped[str] = mapped_column(String(50))
    number: Mapped[str] = mapped_column(String(50))
    heading: Mapped[str] = mapped_column(String(500))
    nominal_level: Mapped[int] = mapped_column(Integer)
    depth: Mapped[int] = mapped_column(Integer)
    numbering_gap: Mapped[bool] = mapped_column(default=False)
    position: Mapped[int] = mapped_column(Integer)
    body_text: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    blocks: Mapped[list] = mapped_column(JSON, default=list)
    document_version: Mapped[DocumentVersion] = relationship(back_populates="nodes")
    logical_node: Mapped[LogicalNode] = relationship(back_populates="snapshots")
    parent: Mapped["Node | None"] = relationship(remote_side="Node.id", foreign_keys=[parent_node_id])


class Selection(Base):
    __tablename__ = "selections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    items: Mapped[list["SelectionItem"]] = relationship(back_populates="selection", cascade="all, delete-orphan")


class SelectionItem(Base):
    __tablename__ = "selection_items"
    __table_args__ = (UniqueConstraint("selection_id", "node_id", name="uq_selection_node"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    selection_id: Mapped[str] = mapped_column(ForeignKey("selections.id"), index=True)
    # This snapshot node ID pins the version; a logical-node ID alone would not.
    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.id"), index=True)
    selection: Mapped[Selection] = relationship(back_populates="items")
    node: Mapped[Node] = relationship()
