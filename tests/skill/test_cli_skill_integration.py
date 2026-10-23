# ABOUTME: Integration tests that check every calendar-cli command written in the calendar-cli skill
# ABOUTME: against the real Typer app, so the skill never teaches a command or option that does not exist.
import re
import shlex

import pytest
import typer

from calendar_cli.cli import app
from tests.skill.test_cli_skill_unit import SKILL_PATH

COMMANDS = typer.main.get_command(app).commands


def skill_commands() -> list[str]:
    """Every `calendar-cli ...` command in SKILL.md, from fenced blocks and inline code."""
    text = SKILL_PATH.read_text()
    found = []
    for block in re.findall(r"```zsh\n(.*?)```", text, re.DOTALL):
        for line in block.replace("\\\n", " ").splitlines():
            if line.strip().startswith("calendar-cli "):
                found.append(line.strip())
    found += re.findall(r"`(calendar-cli [^`]+)`", text)
    # Placeholders such as `calendar-cli COMMAND --help` and `calendar-cli ... --config` are prose.
    return [c for c in found if not re.match(r"calendar-cli (\.\.\.|[A-Z])", c)]


def check(command: str) -> None:
    tokens = shlex.split(command, comments=True)
    assert tokens[1] in COMMANDS, f"unknown command in: {command}"
    params = {}
    for param in COMMANDS[tokens[1]].params:
        for opt in [*getattr(param, "opts", []), *getattr(param, "secondary_opts", [])]:
            params[opt] = param
    params["--help"] = None
    rest = iter(tokens[2:])
    for token in rest:
        if not token.startswith("-") or token == "-" or re.fullmatch(r"[+-]\d+[dw]", token):
            continue
        assert token in params, f"unknown option {token} in: {command}"
        param = params[token]
        if param is not None and not param.is_flag:
            next(rest, None)


def test_skill_has_commands_to_check():
    assert len(skill_commands()) >= 15


@pytest.mark.parametrize("command", skill_commands())
def test_command_is_valid(command):
    check(command)


def test_check_rejects_an_unknown_option():
    with pytest.raises(AssertionError, match="unknown option --colour"):
        check("calendar-cli add X -c work -s today --colour red")


def test_check_rejects_an_unknown_command():
    with pytest.raises(AssertionError, match="unknown command"):
        check("calendar-cli show work:1")
