from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str = "sqlite:///./ct200.db"):
    return create_engine(database_url, connect_args={"check_same_thread": False})


def create_schema(engine) -> None:
    # Import registers model metadata without creating a circular dependency.
    from app import models  # noqa: F401

    Base.metadata.create_all(engine)


def make_session_factory(database_url: str = "sqlite:///./ct200.db"):
    engine = make_engine(database_url)
    create_schema(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
