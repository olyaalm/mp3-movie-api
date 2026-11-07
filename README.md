# MP3 Movie API

This FastAPI application stores one collection of movies in a SQLite database. Uploading another CSV replaces the current collection. Unlike MP2's in-memory storage, the movies remain available after the server restarts.

## Setup And Run

From the project directory in PowerShell:

```powershell
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload
```

Open `http://127.0.0.1:8000/docs` to try the endpoints. SQLite creates `data/movies.db` automatically; that local database is not committed to Git.

## Try The API

1. Use `POST /upload` to upload `fixtures/sample_movies.csv`. The response should show 20 rows and the four fields `title`, `release_year`, `rating`, and `genre`.
2. Use `GET /movies` with `limit=2` to see Movie A and Movie B; `total_rows` should be 20.
3. Use `GET /movies/search` with `min_rating=8.5` and `limit=2`. Movie C appears first, followed by Movie B. Add `title` and `rating` as separate `columns` items to show both fields.
4. Restart the server and call `GET /movies` again. The collection should still be there. Uploading the sample again replaces it instead of creating 40 rows.
5. To clean the data, use `POST /movies/process` with the request below. The two repeated movie rows are removed, leaving 18 rows.

```json
{
  "validation": {
    "required_columns": ["title", "release_year", "rating", "genre"],
    "numeric_columns": ["release_year", "rating"]
  },
  "processing": {
    "remove_duplicates": true,
    "missing": {"enabled": true, "axis": "rows"},
    "outliers": {"enabled": false, "columns": [], "method": "iqr", "threshold": 1.5}
  }
}
```

`GET /health` checks that the API is running. Invalid uploads and unsupported search columns return HTTP 400; each response includes an `X-Request-ID` header for finding its log entry.

## Tests

```powershell
python -m pytest tests -v
```

The tests use temporary SQLite files and do not overwrite your saved movie collection.