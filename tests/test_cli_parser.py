import argparse
import importlib.metadata

import pytest

from mailbrief.main import build_parser


def test_build_parser_has_no_setup_side_effects(monkeypatch):
    import mailbrief.main as cli

    monkeypatch.setattr(cli, "load_dotenv", lambda: (_ for _ in ()).throw(AssertionError("read .env")))
    parser = build_parser()
    assert parser.prog == "mailbrief"
    assert parser.parse_args(["stop"]).command == "stop"


def test_version_comes_from_package_metadata(monkeypatch, capsys):
    monkeypatch.setattr(importlib.metadata, "version", lambda name: "9.8.7")
    with pytest.raises(SystemExit) as stopped:
        build_parser().parse_args(["--version"])
    assert stopped.value.code == 0
    assert "mailbrief 9.8.7" in capsys.readouterr().out


def test_version_falls_back_when_not_installed(monkeypatch, capsys):
    def missing(name):
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", missing)
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--version"])
    assert "mailbrief (not installed)" in capsys.readouterr().out


def test_parses_command_values_and_defaults():
    parser = build_parser()
    args = parser.parse_args(
        ["run", "--digest", "this-week", "--send", "--commit", "--as-of", "2026-11-20"]
    )
    assert (args.command, args.digest_scope, args.send, args.commit) == ("run", "this-week", True, True)
    assert str(args.as_of) == "2026-11-20" and args.quiet is False and args.plain is False

    labels = parser.parse_args(["labels", "clear", "--days", "7", "--limit", "2", "--label", "MA1521"])
    assert (labels.command, labels.action, labels.days, labels.limit) == ("labels", "clear", 7, 2)
    assert labels.label == "MA1521" and labels.colours is False

    rule = parser.parse_args(["rules", "add", "topic", "Networking", "career fairs, meetups"])
    assert (rule.kind, rule.key, rule.description) == ("topic", "Networking", "career fairs, meetups")

    chat = parser.parse_args(["chat"])
    assert chat.question is None


def test_required_and_mutually_exclusive_arguments_still_fail():
    parser = build_parser()
    with pytest.raises(SystemExit) as missing:
        parser.parse_args([])
    assert missing.value.code == 2
    with pytest.raises(SystemExit):
        parser.parse_args(["emails", "--show", "1", "--thread", "2"])
    with pytest.raises(SystemExit):
        parser.parse_args(["labels", "apply", "--limit", "0"])
    with pytest.raises(SystemExit):
        parser.parse_args(["add-destination", "email"])


def test_hidden_flag_parses_but_stays_out_of_help():
    parser = build_parser()
    args = parser.parse_args(["run", "--no-password"])
    assert args.plain is True
    run_parser = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    ).choices["run"]
    assert "--no-password" not in run_parser.format_help()
    assert "--plain" in run_parser.format_help()
