"""Фикстуры тестов: изолированная БД, переопределение get_db."""
from __future__ import annotations

import os

_TMP = os.path.join(os.path.dirname(__file__), ".tmp")
os.makedirs(_TMP, exist_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP, 'test.db')}"
os.environ["APP_DATA_DIR"] = _TMP
os.environ["APP_FIRST_ADMIN_LOGIN"] = "admin"
os.environ["APP_FIRST_ADMIN_PASSWORD"] = "admin-pass-123"
os.environ["APP_FIRST_ADMIN_NAME"] = "Test Admin"
os.environ["APP_ENV"] = "test"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.db import models  # noqa: F401,E402
from app.db.base import Base  # noqa: E402
from app.deps import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.services.bootstrap import bootstrap  # noqa: E402

engine = create_engine(
    os.environ["DATABASE_URL"], connect_args={"check_same_thread": False}, poolclass=NullPool
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = TestingSessionLocal()
    bootstrap(db)
    db.close()

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)
