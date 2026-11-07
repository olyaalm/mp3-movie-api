"""Tests for the movie API, SQL queries, and SQLite persistence."""

import sqlite3

import pandas as pd
import pytest

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


def test_failed_processing_preserves_collection(client, uploaded_movies):
    """Invalid processing settings do not replace the saved movie table."""
    before = client.get("/movies").json()
    response = client.post("/movies/process", json={"processing": {"missing": {"enabled": True, "axis": "invalid"}}})
    assert response.status_code == 400
    assert client.get("/movies").json() == before


def test_storage_persists_and_handles_null(movie_storage):
    """Reopening a database retains movies and preserves missing values as NULL."""
    movie_storage.save(pd.DataFrame([["Example", None, None, "Drama"]], columns=MOVIE_COLUMNS))
    reopened = MovieStorage(movie_storage.db_path)
    assert reopened.count_movies() == 1
    assert reopened.select_columns(MOVIE_COLUMNS)[0] == {"id": 1, "title": "Example", "release_year": None, "rating": None, "genre": "Drama"}


def test_storage_rolls_back_failed_insert(movie_storage):
    """A failed insert rolls back the delete and keeps the previous collection."""
    movie_storage.save(pd.DataFrame([["Original", 2020, 8.0, "Drama"]], columns=MOVIE_COLUMNS))
    invalid = pd.DataFrame([[{"unsupported": "value"}, 2021, 9.0, "Comedy"]], columns=MOVIE_COLUMNS)
    with pytest.raises(sqlite3.Error):
        movie_storage.save(invalid)
    assert movie_storage.select_columns(["title"]) == [{"id": 1, "title": "Original"}]


def test_storage_rejects_empty_or_invalid_columns(movie_storage):
    """Only known column names can be included in generated SQL."""
    for columns in ([], ["unknown"]):
        with pytest.raises(ValueError):
            movie_storage.select_columns(columns)
        with pytest.raises(ValueError):
            movie_storage.query_movies(columns, 0, 5)