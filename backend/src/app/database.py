from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os

from app.models import metadata


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@db:5432/agent_tests",
)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_db() -> None:
    """Create database schema using the enhanced metadata."""
    metadata.create_all(engine)
