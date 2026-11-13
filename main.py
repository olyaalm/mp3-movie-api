"""FastAPI endpoints for uploading, finding, and cleaning movies."""

import io
import logging
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, File, HTTPException, Query, UploadFile

from data_pipeline import create_cleaning_report, process_data, validate_dataframe
from src import (
    HealthResponse,
        MovieCache,
    MovieDataResponse,
    MovieProcessingReport,
    MovieStorage,
    MovieUploadInfo,
    ProcessConfig,
    log_requests,
    setup_logging,
)
from src.storage import MOVIE_COLUMNS


setup_logging(verbose=True)
logger = logging.getLogger(__name__)
app = FastAPI(title="Movie API", version="1.0.0")
app.middleware("http")(log_requests)
storage = MovieStorage()
cache = MovieCache()


@app.get("/health", response_model=HealthResponse)
def health_check():
    """Return the API status and version."""
    return {"status": "ok", "version": "1.0.0"}


@app.post("/upload", response_model=MovieUploadInfo)
async def upload_movies(file: UploadFile = File(...)):
    """Read a movie CSV and replace the saved collection.

    Args:
        file: Uploaded CSV file containing the four movie columns.

    Returns:
        dict: Filename, row count, column count, and column names.

    Raises:
        HTTPException: If the file is not a valid, non-empty movie CSV.
    """
    filename = file.filename or ""
    if Path(filename).suffix.lower() != ".csv":
        logger.warning("Unsupported file format: %s", filename)
        raise HTTPException(status_code=400, detail="Only CSV files are supported.")

    contents = await file.read()
    try:
        df = pd.read_csv(io.BytesIO(contents))
    except (pd.errors.EmptyDataError, pd.errors.ParserError, UnicodeDecodeError) as error:
        logger.warning("Could not read uploaded CSV %s: %s", filename, error)
        raise HTTPException(status_code=400, detail="The uploaded file is not a readable CSV.") from error

    if len(df.columns) != len(MOVIE_COLUMNS) or set(df.columns) != set(MOVIE_COLUMNS):
        raise HTTPException(status_code=400, detail="CSV must contain exactly title, release_year, rating, and genre.")
    if df.empty:
        raise HTTPException(status_code=400, detail="CSV must contain at least one movie.")

    # Keep the database unchanged until the input passes both checks.
    df = df[MOVIE_COLUMNS]
    storage.save(df)
    cache.invalidate()
    logger.info("Uploaded movies: filename=%s, rows=%s", filename, len(df))
    return {
        "filename": filename,
        "rows": len(df),
        "columns": len(df.columns),
        "column_names": list(df.columns),
    }


@app.get("/movies", response_model=MovieDataResponse)
def get_movies(limit: int = Query(default=100, ge=1)):
    """Return movie rows in ID order and the full collection count.

    Args:
        limit: Maximum number of rows to return, at least one.

    Returns:
        dict: Movie records and the total number stored.
    """
    cached_response = cache.get(limit)
    if cached_response is not None:
        logger.info("Returned cached movies: limit=%s", limit)
        return cached_response

    rows = storage.select_columns(MOVIE_COLUMNS, limit)
    logger.info("Retrieved movies: returned_rows=%s", len(rows))
    response = {"data": rows, "total_rows": storage.count_movies()}
    cache.set(limit, response)
    return response


@app.get("/movies/search", response_model=list[dict])
def query_movies(
    columns: list[str] = Query(default=["title"]),
    min_rating: float = Query(default=0, ge=0, le=10),
    limit: int = Query(default=100, ge=1),
):
    """Search movies by rating and return only the chosen fields.

    Args:
        columns: Movie fields to return alongside each ID.
        min_rating: Lowest rating to include, from zero to ten.
        limit: Maximum number of matching movies to return.

    Returns:
        list[dict]: Matching movies sorted by rating and ID.

    Raises:
        HTTPException: If a requested column is unsupported.
    """
    try:
        rows = storage.query_movies(columns, min_rating, limit)
    except ValueError as error:
        logger.warning("Invalid movie search: %s", error)
        raise HTTPException(status_code=400, detail=str(error)) from error
    logger.info("Queried movies: columns=%s, min_rating=%s, returned_rows=%s", columns, min_rating, len(rows))
    return rows


@app.post("/movies/process", response_model=MovieProcessingReport)
def process_movies(config: ProcessConfig):
    """Validate and clean the stored movie collection.

    Args:
        config: Required columns, numeric columns, and cleaning settings.

    Returns:
        dict: Validation removals and a separate cleaning report.

    Raises:
        HTTPException: If the collection is empty or settings are invalid.
    """
    df = storage.get()
    if df.empty:
        raise HTTPException(status_code=400, detail="No movies have been uploaded.")

    settings = config.model_dump()
    validation = settings["validation"]
    try:
        missing_numeric = [column for column in validation["numeric_columns"] if column not in df.columns]
        if missing_numeric:
            raise ValueError(f"Numeric columns not found: {missing_numeric}")
        validated = validate_dataframe(df, validation["required_columns"], validation["numeric_columns"])
        validation_removed = len(df) - len(validated)
        before_processing = validated.copy()
        processed = process_data(validated, settings)
        report = create_cleaning_report(before_processing, processed)
        storage.save(processed)
        cache.invalidate()
    except ValueError as error:
        logger.warning("Movie processing rejected: %s", error)
        raise HTTPException(status_code=400, detail=str(error)) from error

    logger.info("Processed movies: validation_rows_removed=%s, rows_before=%s, rows_after=%s", validation_removed, report["rows_before"], report["rows_after"])
    return {"validation_rows_removed": validation_removed, "cleaning_report": report}