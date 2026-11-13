# MP3 Movie API
This FastAPI application manages one movie collection and exposes upload, retrieval, search, processing, and health endpoints. `main.py` validates uploaded CSV files, coordinates storage and processing, and serves the API documented at `/docs`. The `data_pipeline/` package validates movie fields and applies duplicate, missing-value, and outlier handling. `src/storage.py` replaces and queries the collection in SQLite, while `src/database.py` creates the persistent table and connections. `src/cache.py` stores only `GET /movies` responses by limit for 90 seconds, and successful uploads or processing invalidate every cached response. `src/models.py` defines request and response schemas, and `src/middleware.py` adds request IDs to logs and responses. The tests use temporary SQLite databases and isolated in-memory caches to check persistence, retrieval, processing, and cache behavior.

## Setup And Run

From the project directory in PowerShell:

```powershell
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload
```

Open `http://127.0.0.1:8000/docs` to try the endpoints. SQLite creates `data/movies.db` automatically; that local database is not committed to Git.

## Processing Example

Upload `fixtures/sample_movies.csv` with `POST /upload`, then send this request to `POST /movies/process`:

```json
{
  "validation": {
    "required_columns": ["title", "release_year", "rating", "genre"],
    "numeric_columns": ["release_year", "rating"]
  },
  "processing": {
    "remove_duplicates": true,
    "missing": {"enabled": true, "axis": "rows"},
    "outliers": {
      "enabled": true,
      "columns": ["rating"],
      "method": "iqr",
      "threshold": 1.5
    }
  }
}
```

The 20-row sample has no validation removals. Duplicate and rating-outlier cleanup removes four rows, so the response reports `rows_before: 20`, `rows_after: 16`, `rows_removed: 4`, `columns_before: 4`, `columns_after: 4`, and `columns_removed: 0`. After processing, `GET /movies?limit=100` returns 16 records and `total_rows: 16`; repeating the request is a cache hit. Restarting the server preserves those 16 SQLite rows, while uploading the sample again replaces them with 20 rows and clears cached retrievals.

## Tests

```powershell
python -m pytest tests -v
```