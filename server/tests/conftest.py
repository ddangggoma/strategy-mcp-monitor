from datetime import datetime, timezone

import pytest

from app.db import Database
from app.paths import AppPaths
from tests.fakes import FakeClock


@pytest.fixture
def clock():
    return FakeClock(datetime(2026, 11, 4, 5, 0, 0, tzinfo=timezone.utc))


@pytest.fixture
def paths(tmp_path):
    p = AppPaths(tmp_path)
    p.ensure()
    return p


@pytest.fixture
def db(paths):
    database = Database(paths.db_path)
    database.migrate()
    yield database
    database.close()
