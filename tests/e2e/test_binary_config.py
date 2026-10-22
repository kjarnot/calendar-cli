# ABOUTME: End-to-end tests that run the installed calendar-cli executable as a subprocess.
# ABOUTME: These use temporary configs only and never contact a real calendar.
import shutil
import subprocess

import pytest

BINARY = shutil.which("calendar-cli")

pytestmark = pytest.mark.skipif(BINARY is None, reason="calendar-cli is not installed in this environment")


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([BINARY, *args], check=False, capture_output=True, text=True, timeout=30)


def test_help_lists_config_command():
    result = run("--help")

    assert result.returncode == 0
    assert "config" in result.stdout


def test_config_command_via_binary(write_config):
    result = run("config", "--config", str(write_config()))

    assert result.returncode == 0, result.stderr
    assert "personal  -> gmail:primary" in result.stdout
    assert result.stderr == ""


def test_config_error_goes_to_stderr(write_config):
    result = run("config", "--config", str(write_config(mode=0o644)))

    assert result.returncode == 1
    assert "chmod 600" in result.stderr
    assert result.stdout == ""
