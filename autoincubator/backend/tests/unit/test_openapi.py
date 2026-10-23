"""The committed backend/openapi.json matches the running app's schema."""

from scripts.export_openapi import OPENAPI_PATH, render


def test_committed_openapi_schema_is_current() -> None:
    assert OPENAPI_PATH.read_text() == render(), (
        "openapi.json is stale: run `make openapi` and commit the result"
    )
