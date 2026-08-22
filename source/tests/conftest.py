from __future__ import annotations

import pytest

import database


@pytest.fixture(autouse=True)
def isolated_database(tmp_path):
    """Give every test a complete database without touching the user's DB.

    A few UI/API tests only read configuration and previously depended on the
    order of another test creating the schema first.  Starting every test from
    a fresh schema makes the suite deterministic and keeps clean-install runs
    inside pytest's temporary directory.
    """
    original_path = database.get_db_path()
    database.set_db_path(tmp_path / "komi-report-v5-test.sqlite3")
    database.init_db()
    try:
        yield
    finally:
        database.set_db_path(original_path)
