"""Tests for the movie API, SQL queries, and SQLite persistence."""

import sqlite3
import string
from pathlib import Path

import pandas as pd
import pytest
import main

from src import MovieStorage
from src.storage import MOVIE_COLUMNS


def test_empty_collection_and_health(client):
    """Check that an empty database returns no movies and health stays available."""
    assert client.get("/movies").json() == {"data": [], "total_rows": 0}
    assert client.post("/movies/process", json={}).status_code == 400
    health = client.get("/health")
    assert health.status_code == 200
    assert health.headers["X-Request-ID"]


def test_upload_and_retrieve_movies(client, uploaded_movies):
    """Check the sample's metadata and the first two movies in ID order."""
    assert uploaded_movies == {
        "filename": "sample_movies.csv",
        "rows": 20,
        "columns": 4,
        "column_names": MOVIE_COLUMNS,
    }
    response = client.get("/movies", params={"limit": 2})
    assert response.status_code == 200
    assert response.json() == {
        "data": [
            {"id": 1, "title": "Movie A", "release_year": 2020, "rating": 8.0, "genre": "Drama"},
            {"id": 2, "title": "Movie B", "release_year": 2021, "rating": 8.5, "genre": "Comedy"},
        ],
        "total_rows": 20,
    }


def test_search_movies(client, uploaded_movies):
    """Check rating filtering, descending sort, limits, and selected columns."""
    default = client.get("/movies/search", params={"min_rating": 8.5, "limit": 2})
    assert default.json() == [{"id": 4, "title": "Movie C"}, {"id": 2, "title": "Movie B"}]
    selected = client.get("/movies/search", params=[("columns", "title"), ("columns", "rating"), ("min_rating", 8.5), ("limit", 2)])
    assert selected.json() == [{"id": 4, "title": "Movie C", "rating": 9.0}, {"id": 2, "title": "Movie B", "rating": 8.5}]
    assert client.get("/movies/search", params={"min_rating": 10}).json() == []


def test_search_rejects_bad_columns_and_invalid_query(client, uploaded_movies):
    """Reject unsupported column names and invalid query parameter values."""
    assert client.get("/movies/search", params={"columns": "id; DROP TABLE movies"}).status_code == 400
    assert client.get("/movies/search", params={"min_rating": 11}).status_code == 422
    assert client.get("/movies", params={"limit": 0}).status_code == 422
    assert client.get("/movies").json()["total_rows"] == 20


def test_repeated_upload_replaces_collection(client, sample_csv_bytes):
    """Uploading the same file twice replaces the rows rather than adding them."""
    for _ in range(2):
        response = client.post("/upload", files={"file": ("sample_movies.csv", sample_csv_bytes, "text/csv")})
        assert response.status_code == 200
    assert client.get("/movies").json()["total_rows"] == 20


@pytest.mark.parametrize("filename,contents", [
    ("notes.txt", b"not csv"),
    ("empty.csv", b""),
    ("headers.csv", b"title,release_year,rating,genre\n"),
    ("wrong.csv", b"title,rating\nMovie A,8\n"),
    ("extra.csv", b"title,release_year,rating,genre,extra\nA,2020,8,Drama,x\n"),
    ("malformed.csv", b'"unclosed'),
    ("encoding.csv", b"\xff\xfe\xff"),
])
def test_invalid_upload_preserves_existing_movies(client, uploaded_movies, filename, contents):
    """Invalid uploads return 400 without replacing the existing collection."""
    response = client.post("/upload", files={"file": (filename, contents, "text/csv")})
    assert response.status_code == 400
    assert response.headers["X-Request-ID"]
    assert client.get("/movies").json()["total_rows"] == 20
    assert client.get("/health").status_code == 200


def test_process_and_retrieve(client, uploaded_movies):
    """Run MP1 validation and duplicate cleaning on the stored collection."""
    config = {
        "validation": {"required_columns": ["title", "rating"], "numeric_columns": ["rating"]},
        "processing": {"remove_duplicates": True, "missing": {"enabled": True, "axis": "rows"}, "outliers": {"enabled": False}},
    }
    response = client.post("/movies/process", json=config)
    assert response.status_code == 200
    assert response.json()["validation_rows_removed"] == 0
    assert response.json()["cleaning_report"]["rows_before"] == 20
    assert response.json()["cleaning_report"]["rows_after"] == 18
    assert client.get("/movies").json()["total_rows"] == 18


def test_movies_persist(client, test_storage, uploaded_movies):
    """Confirm SQLite persistence, source order, columns, and returned IDs."""
    reopened_storage = MovieStorage(test_storage.db_path)
    saved_movies = reopened_storage.get()
    original_movies = pd.read_csv(Path(__file__).resolve().parent.parent / "fixtures" / "sample_movies.csv")

    assert reopened_storage.count_movies() == 20
    assert saved_movies.columns.tolist() == MOVIE_COLUMNS
    assert saved_movies["title"].tolist() == original_movies["title"].tolist()

    persisted_ids = [movie["id"] for movie in reopened_storage.select_columns(MOVIE_COLUMNS, limit=100)]
    response = client.get("/movies", params={"limit": 100})
    assert response.status_code == 200
    response_ids = [movie["id"] for movie in response.json()["data"]]
    assert persisted_ids == list(range(1, 21))
    assert response_ids == persisted_ids


def test_cache_and_processing(client, uploaded_movies, processing_body):
    """Check limit-specific hits and invalidation after processing is saved."""
    response_100 = client.get("/movies", params={"limit": 100})
    response_1 = client.get("/movies", params={"limit": 1})
    assert response_100.status_code == response_1.status_code == 200
    assert main.cache.get(100) == response_100.json()
    assert main.cache.get(1) == response_1.json()

    repeated_100 = client.get("/movies", params={"limit": 100})
    assert repeated_100.status_code == 200
    assert repeated_100.json() == response_100.json()

    processed = client.post("/movies/process", json=processing_body)
    assert processed.status_code == 200
    assert processed.json() == {
        "validation_rows_removed": 0,
        "cleaning_report": {
            "rows_before": 20,
            "rows_after": 16,
            "rows_removed": 4,
            "columns_before": 4,
            "columns_after": 4,
            "columns_removed": 0,
        },
    }
    assert main.cache.get(100) is None
    assert main.cache.get(1) is None

    updated = client.get("/movies", params={"limit": 100})
    assert updated.status_code == 200
    updated_body = updated.json()
    assert updated_body["total_rows"] == 16
    assert [movie["title"] for movie in updated_body["data"]] == [
        f"Movie {letter}" for letter in string.ascii_uppercase[:16]
    ]
    assert [movie["id"] for movie in updated_body["data"]] == list(range(1, 17))
    assert main.cache.get(100) == updated_body


def test_cache_hit_skips_database(client, uploaded_movies, monkeypatch):
    """Verify a repeated movie retrieval returns without querying SQLite."""
    first_response = client.get("/movies", params={"limit": 100})
    assert first_response.status_code == 200

    def fail_database_read(*args, **kwargs):
        pytest.fail("A cache hit should not read from SQLite")

    monkeypatch.setattr(main.storage, "select_columns", fail_database_read)
    monkeypatch.setattr(main.storage, "count_movies", fail_database_read)

    repeated_response = client.get("/movies", params={"limit": 100})
    assert repeated_response.status_code == 200
    assert repeated_response.json() == first_response.json()


def test_failed_processing_preserves_collection(client, uploaded_movies):
    """Invalid processing settings do not replace the saved movie table."""
    before = client.get("/movies").json()
    response = client.post("/movies/process", json={"processing": {"missing": {"enabled": True, "axis": "invalid"}}})
    assert response.status_code == 400
    assert client.get("/movies").json() == before


def test_storage_persists_and_handles_null(test_storage):
    """Reopening a database retains movies and preserves missing values as NULL."""
    test_storage.save(pd.DataFrame([["Example", None, None, "Drama"]], columns=MOVIE_COLUMNS))
    reopened = MovieStorage(test_storage.db_path)
    assert reopened.count_movies() == 1
    assert reopened.select_columns(MOVIE_COLUMNS)[0] == {"id": 1, "title": "Example", "release_year": None, "rating": None, "genre": "Drama"}


def test_storage_rolls_back_failed_insert(test_storage):
    """A failed insert rolls back the delete and keeps the previous collection."""
    test_storage.save(pd.DataFrame([["Original", 2020, 8.0, "Drama"]], columns=MOVIE_COLUMNS))
    invalid = pd.DataFrame([[{"unsupported": "value"}, 2021, 9.0, "Comedy"]], columns=MOVIE_COLUMNS)
    with pytest.raises(sqlite3.Error):
        test_storage.save(invalid)
    assert test_storage.select_columns(["title"]) == [{"id": 1, "title": "Original"}]


def test_storage_rejects_empty_or_invalid_columns(test_storage):
    """Only known column names can be included in generated SQL."""
    for columns in ([], ["unknown"]):
        with pytest.raises(ValueError):
            test_storage.select_columns(columns)
        with pytest.raises(ValueError):
            test_storage.query_movies(columns, 0, 5)