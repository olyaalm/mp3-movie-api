"""Shared, isolated test fixtures for the movie API."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from src import MovieCache, MovieStorage


@pytest.fixture
def test_storage(tmp_path):
    """Return a fresh SQLite database in pytest's temporary directory."""
    return MovieStorage(tmp_path / "test_movies.db")


@pytest.fixture
def client(test_storage, monkeypatch):
    """Use isolated storage and cache so tests cannot change real data."""
    monkeypatch.setattr(main, "storage", test_storage)
    monkeypatch.setattr(main, "cache", MovieCache())
    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture
def sample_csv_bytes():
    """Read the supplied 20-row movie CSV for upload tests."""
    return (Path(__file__).resolve().parent.parent / "fixtures" / "sample_movies.csv").read_bytes()


@pytest.fixture
def uploaded_movies(client, sample_csv_bytes):
    """Upload the sample movie collection for a test."""
    response = client.post("/upload", files={"file": ("sample_movies.csv", sample_csv_bytes, "text/csv")})
    assert response.status_code == 200
    return response.json()


@pytest.fixture
def processing_body():
    """Configure required movie fields, duplicate cleanup, and rating outliers."""
    return {
        "validation": {
            "required_columns": ["title", "release_year", "rating", "genre"],
            "numeric_columns": ["release_year", "rating"],
        },
        "processing": {
            "remove_duplicates": True,
            "missing": {"enabled": True, "axis": "rows"},
            "outliers": {
                "enabled": True,
                "columns": ["rating"],
                "method": "iqr",
                "threshold": 1.5,
            },
        },
    }