from collections.abc import Iterator

import pytest

from tests.fake_server import FakeServer


@pytest.fixture
def fake_server() -> Iterator[FakeServer]:
    server = FakeServer()
    server.start()
    try:
        yield server
    finally:
        server.stop()
