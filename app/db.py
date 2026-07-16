from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str = "sqlite:///./ct200.db"):
    return create_engine(database_url, connect_args={"check_same_thread": False})


def create_schema(engine) -> None:
    # Import registers model metadata without creating a circular dependency.
    from app import models  # noqa: F401

    Base.metadata.create_all(engine)
    # Lightweight forward migration for databases created before document
    # title retention was added. Alembic would replace this in production.
    columns = {column["name"] for column in inspect(engine).get_columns("documents")}
    if "title" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE documents ADD COLUMN title VARCHAR(500) NOT NULL DEFAULT ''"))


def make_session_factory(database_url: str = "sqlite:///./ct200.db"):
    engine = make_engine(database_url)
    create_schema(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
