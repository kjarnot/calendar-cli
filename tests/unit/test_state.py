# ABOUTME: Unit tests for local state: saving and resolving short refs, and app log setup.
# ABOUTME: The autouse isolated_state fixture points the state directory at a temp folder.
import logging
import stat
from datetime import UTC, datetime, timedelta

import pytest

from calendar_cli.state import RefError, resolve_ref, save_refs, setup_logging


def test_save_and_resolve_ref(isolated_state):
    save_refs({"work:1": ("work", "AAMk-long-id")})

    assert resolve_ref("work:1") == ("work", "AAMk-long-id")
    assert stat.S_IMODE((isolated_state / "refs.json").stat().st_mode) == 0o600


def test_resolve_without_listing_raises():
    with pytest.raises(RefError, match="run `calendar-cli list` first"):
        resolve_ref("work:1")


def test_unknown_ref_raises():
    save_refs({"work:1": ("work", "id")})

    with pytest.raises(RefError, match="unknown ref 'work:9'"):
        resolve_ref("work:9")


def test_stale_listing_raises():
    save_refs({"work:1": ("work", "id")})

    with pytest.raises(RefError, match="older than 24 hours"):
        resolve_ref("work:1", now=datetime.now(UTC) + timedelta(hours=25))


def test_setup_logging_writes_private_app_log(isolated_state):
    setup_logging()
    logging.getLogger("calendar_cli.test").info("hello log")

    log_path = isolated_state / "app.log"
    assert "INFO calendar_cli.test: hello log" in log_path.read_text()
    assert stat.S_IMODE(log_path.stat().st_mode) == 0o600
