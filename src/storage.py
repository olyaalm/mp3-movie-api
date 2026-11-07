"""Store and query one movie collection in SQLite."""

import logging
import sqlite3

import pandas as pd

from .database import get_connection, initialize_database


logger = logging.getLogger(__name__)
MOVIE_COLUMNS = ["title", "release_year", "rating", "genre"]


def _validate_columns(columns):
    """Check that at least one requested column is a supported movie field.

    Args:
        columns: Movie column names requested by the client.

    Raises:
        ValueError: If the list is empty or contains an unsupported field.
    """
    if not columns:
        raise ValueError("Select at least one column")
    for column in columns:
        if column not in MOVIE_COLUMNS:
            raise ValueError(f"Unsupported column: {column}")


class MovieStorage:
    """Keep movie records in a persistent SQLite database."""

    def __init__(self, db_path="data/movies.db"):
        """Create the movie table at the chosen database path if needed."""
        self.db_path = db_path
        initialize_database(self.db_path)

    def save(self, df):
        """Replace the collection in one transaction.

        Args:
            df: DataFrame containing the four movie columns.

        Raises:
            ValueError: If a required movie column is missing.
            sqlite3.Error: If SQLite cannot complete the replacement.
        """
        missing_columns = [column for column in MOVIE_COLUMNS if column not in df.columns]
        if missing_columns:
            raise ValueError(f"Movie columns missing: {missing_columns}")

        # Convert pandas missing values to None so SQLite stores them as NULL.
        movies = df[MOVIE_COLUMNS].astype(object).where(pd.notna(df[MOVIE_COLUMNS]), None)
        rows = list(movies.itertuples(index=False, name=None))
        connection = get_connection(self.db_path)
        try:
            connection.execute("DELETE FROM movies")
            connection.executemany(
                "INSERT INTO movies (title, release_year, rating, genre) VALUES (?, ?, ?, ?)",
                rows,
            )
            connection.commit()
            logger.debug("Stored movies in SQLite: rows=%s", len(rows))
        except sqlite3.Error:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get(self):
        """Return all movie fields as a DataFrame, in ID order."""
        connection = get_connection(self.db_path)
        try:
            rows = connection.execute(
                "SELECT title, release_year, rating, genre FROM movies ORDER BY id"
            ).fetchall()
            return pd.DataFrame([tuple(row) for row in rows], columns=MOVIE_COLUMNS)
        finally:
            connection.close()

    def select_columns(self, columns, limit=5):
        """Return IDs and requested movie columns, in ID order.

        Args:
            columns: Supported movie field names to return.
            limit: Maximum number of rows to return.

        Returns:
            list[dict]: Matching movie rows.
        """
        _validate_columns(columns)
        selected_columns = ", ".join(["id"] + columns)
        connection = get_connection(self.db_path)
        try:
            rows = connection.execute(
                f"SELECT {selected_columns} FROM movies ORDER BY id LIMIT ?", (limit,)
            ).fetchall()
            logger.debug("Selected movie columns=%s rows=%s", columns, len(rows))
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def count_movies(self):
        """Return the number of stored movies using SQL COUNT(*)."""
        connection = get_connection(self.db_path)
        try:
            return connection.execute("SELECT COUNT(*) FROM movies").fetchone()[0]
        finally:
            connection.close()

    def query_movies(self, columns, min_rating, limit):
        """Find movies at or above a rating, highest rating first.

        Args:
            columns: Supported movie fields to include along with the ID.
            min_rating: Minimum rating to include.
            limit: Maximum number of rows to return.

        Returns:
            list[dict]: Matching movie rows sorted by rating and ID.
        """
        _validate_columns(columns)
        selected_columns = ", ".join(["id"] + columns)
        connection = get_connection(self.db_path)
        try:
            rows = connection.execute(
                f"SELECT {selected_columns} FROM movies WHERE rating >= ? "
                "ORDER BY rating DESC, id ASC LIMIT ?",
                (min_rating, limit),
            ).fetchall()
            logger.debug("Queried movie columns=%s rows=%s", columns, len(rows))
            return [dict(row) for row in rows]
        finally:
            connection.close()