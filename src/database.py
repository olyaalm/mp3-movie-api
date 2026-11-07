"""Create SQLite connections and the persistent movie table."""

import sqlite3
from pathlib import Path


def get_connection(db_path):
    """Open a database connection with rows accessible by column name.

    Args:
        db_path: Location of the SQLite database file.

    Returns:
        sqlite3.Connection: A new connection to the database.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database(db_path):
    """Create the movies table if it does not already exist.

    Args:
        db_path: Location of the SQLite database file.

    Returns:
        None: Creates the table in the database.
    """
    connection = get_connection(db_path)
    try:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS movies (
                id INTEGER PRIMARY KEY,
                title TEXT,
                release_year INTEGER,
                rating REAL,
                genre TEXT
            )"""
        )
        connection.commit()
    finally:
        connection.close()