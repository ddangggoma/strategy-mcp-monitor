from datetime import datetime, timezone

import httpx
import pytest
import pytest_asyncio

from app.db import Database
from app.paths import AppPaths
from app.services import build_services
from app.web.app_factory import create_app
from tests.fakes import CapturingOtpProvider, FakeClock


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


@pytest_asyncio.fixture
async def services(tmp_path, clock):
    svc = build_services(tmp_path, clock=clock, otp_provider=CapturingOtpProvider())
    await svc.log.start()
    yield svc
    await svc.log.stop()
    svc.db.close()


@pytest_asyncio.fixture
async def local_client(services):
    transport = httpx.ASGITransport(app=create_app("local", services))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8700") as client:
        yield client


@pytest_asyncio.fixture
async def external_client(services):
    transport = httpx.ASGITransport(app=create_app("external", services))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
