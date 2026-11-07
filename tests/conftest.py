"""Shared, isolated test fixtures for the movie API."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from src import MovieStorage


@pytest.fixture
def movie_storage(tmp_path):
    """Return a fresh SQLite database in pytest's temporary directory."""
    return MovieStorage(tmp_path / "movies.db")


@pytest.fixture
def client(monkeypatch, movie_storage):
    """Use a test database so tests never change the real movie collection."""
    monkeypatch.setattr(main, "storage", movie_storage)
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