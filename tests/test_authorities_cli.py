from __future__ import annotations

from pathlib import Path

import pytest


def test_parse_args_accepts_subcommand_regenerate(cli_module) -> None:
    args = cli_module.parse_args(["regenerate", "person_4815", "person_4805"])

    assert args.command == "regenerate"
    assert args.entries == ["person_4815", "person_4805"]


def test_parse_args_accepts_reconcile_apply_report_flag(cli_module) -> None:
    args = cli_module.parse_args(
        [
            "reconcile",
            "--apply",
            "--report",
            "processing/authority_enrichment_report.json",
        ]
    )

    assert args.command == "reconcile"
    assert args.apply is True
    assert args.report == Path("processing/authority_enrichment_report.json")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Carne, Sir Edward, 1496?–1561", "Carne, Sir Edward"),
        ("Geoffrey Brito, fl. 1220s–1240s", "Geoffrey Brito"),
        ("Price, Gregory, 1535–1600", "Price, Gregory"),
    ],
)
def test_strip_existing_person_date_suffix(
    module, raw: str, expected: str
) -> None:
    assert module.strip_existing_person_date_suffix(raw) == expected
