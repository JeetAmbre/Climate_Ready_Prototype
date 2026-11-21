"""
models/__init__.py - Database models & connection pooling.
Re-exports core SQLAlchemy entities for clean modular imports.
"""
from database import (
    Base,
    User,
    ProjectModel,
    InterventionModel,
    DecisionPlanModel,
    SessionLocal,
    engine,
    init_db,
    get_database_url,
    get_fallback_sqlite,
)

__all__ = [
    "Base",
    "User",
    "ProjectModel",
    "InterventionModel",
    "DecisionPlanModel",
    "SessionLocal",
    "engine",
    "init_db",
    "get_database_url",
    "get_fallback_sqlite",
]
