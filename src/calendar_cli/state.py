# ABOUTME: Local state for calendar-cli: the state directory, the app log, and short event refs.
# ABOUTME: Short refs (work:3) map to full provider IDs from the most recent `list`.
import json
import logging
import os
from datetime import UTC, datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

STATE_ENV_VAR = "CALENDAR_CLI_STATE_DIR"
DEFAULT_STATE_DIR = Path("~/.local/state/calendar-cli").expanduser()
REFS_MAX_AGE = timedelta(hours=24)

logger = logging.getLogger("calendar_cli")


class RefError(Exception):
    """Raised when a short event ref cannot be resolved."""


def state_dir() -> Path:
    path = Path(os.environ[STATE_ENV_VAR]).expanduser() if STATE_ENV_VAR in os.environ else DEFAULT_STATE_DIR
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def private_file(path: Path) -> Path:
    """Create the file if needed and restrict it to the owner, since it holds event data."""
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    return path


def setup_logging(verbose: bool = False) -> None:
    """Send the calendar_cli logger to a rotating app.log in the state directory."""
    if any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
        return
    log_path = private_file(state_dir() / "app.log")
    handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)


def save_refs(refs: dict[str, tuple[str, str]]) -> None:
    """Save short refs as {ref: (calendar_alias, provider_id)}."""
    payload = {
        "saved_at": datetime.now(UTC).isoformat(),
        "refs": {ref: {"calendar": alias, "event_id": event_id} for ref, (alias, event_id) in refs.items()},
    }
    path = private_file(state_dir() / "refs.json")
    path.write_text(json.dumps(payload, indent=2))


def resolve_ref(ref: str, now: datetime | None = None) -> tuple[str, str]:
    """Return (calendar_alias, provider_id) for a short ref from the last listing."""
    path = state_dir() / "refs.json"
    if not path.is_file():
        raise RefError(f"no saved listing to resolve {ref!r}; run `calendar-cli list` first")
    payload = json.loads(path.read_text())
    saved_at = datetime.fromisoformat(payload["saved_at"])
    if (now or datetime.now(UTC)) - saved_at > REFS_MAX_AGE:
        raise RefError(
            f"the saved listing is older than 24 hours; run `calendar-cli list` again to use {ref!r}"
        )
    entry = payload["refs"].get(ref)
    if entry is None:
        raise RefError(f"unknown ref {ref!r}; run `calendar-cli list` to see current refs")
    return entry["calendar"], entry["event_id"]
