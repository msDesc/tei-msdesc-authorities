"""Command-line interface for tei-msdesc-authorities."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .core import run_add, run_enrich, run_reconcile, run_regenerate
from .wikidata import WikidataClient


def add_common_authority_args(parser: argparse.ArgumentParser) -> None:
    """Add shared authority-file and source-selection arguments."""

    parser.add_argument("--persons", type=Path, default=Path("persons.xml"))
    parser.add_argument("--places", type=Path, default=Path("places.xml"))
    parser.add_argument("--works", type=Path, default=Path("works.xml"))
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="Do not call Wikidata; generate labels from local text where possible.",
    )


def add_min_id_args(parser: argparse.ArgumentParser) -> None:
    """Add lower-bound options for newly allocated local numeric IDs."""

    parser.add_argument(
        "--person-min-id",
        type=int,
        default=1,
        help="Minimum numeric ID for newly created person_* keys.",
    )
    parser.add_argument(
        "--place-min-id",
        type=int,
        default=1,
        help="Minimum numeric ID for newly created place_* keys.",
    )
    parser.add_argument(
        "--org-min-id",
        type=int,
        default=1,
        help="Minimum numeric ID for newly created org_* keys.",
    )
    parser.add_argument(
        "--work-min-id",
        type=int,
        default=1,
        help="Minimum numeric ID for newly created work_* keys.",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the public ``authorities`` argument parser."""

    parser = argparse.ArgumentParser(
        description="Manage TEI authority records for msDesc-based projects.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser(
        "add",
        help="Add authority entries directly from Wikidata IDs or URLs.",
    )
    add_common_authority_args(add_parser)
    add_min_id_args(add_parser)
    add_parser.add_argument(
        "refs",
        nargs="+",
        help="One or more Wikidata QIDs/URLs, optionally prefixed with a type such as place:Q145.",
    )
    add_parser.add_argument(
        "--as",
        dest="entity_type",
        choices=["person", "place", "org", "work"],
        help="Force the entity type for all supplied refs.",
    )
    add_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview only; do not write authority files.",
    )
    add_parser.add_argument(
        "--report",
        type=Path,
        default=Path("processing/authority_enrichment_report.json"),
        help="Path for JSON report output.",
    )
    add_parser.set_defaults(handler=run_add)

    enrich_parser = subparsers.add_parser(
        "enrich",
        help="Scan manuscript XML for unresolved refs and enrich authority files.",
    )
    add_common_authority_args(enrich_parser)
    add_min_id_args(enrich_parser)
    enrich_parser.add_argument(
        "inputs",
        nargs="*",
        help="XML files to scan. If omitted, scans collections/**/*.xml.",
    )
    enrich_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview only; do not write manuscript/authority files.",
    )
    enrich_parser.add_argument(
        "--keep-ref",
        action="store_true",
        help="Keep existing @ref attributes when writing manuscript changes.",
    )
    enrich_parser.add_argument(
        "--report",
        type=Path,
        default=Path("processing/authority_enrichment_report.json"),
        help="Path for JSON report output.",
    )
    enrich_parser.set_defaults(handler=run_enrich)

    reconcile_parser = subparsers.add_parser(
        "reconcile",
        help="Report likely Wikidata matches for existing person authorities.",
    )
    add_common_authority_args(reconcile_parser)
    reconcile_parser.add_argument(
        "--report",
        type=Path,
        default=Path("processing/authority_enrichment_report.json"),
        help="Path for JSON report output.",
    )
    reconcile_parser.add_argument(
        "--reconcile-limit",
        type=int,
        default=5,
        help="Maximum Wikidata candidates to include per existing authority entry during reconciliation.",
    )
    reconcile_parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply approved reconciliation matches from the report instead of generating a new one.",
    )
    reconcile_parser.set_defaults(handler=run_reconcile)

    regenerate_parser = subparsers.add_parser(
        "regenerate",
        help="Regenerate existing authority entries from Wikidata.",
    )
    add_common_authority_args(regenerate_parser)
    add_min_id_args(regenerate_parser)
    regenerate_parser.add_argument(
        "entries",
        nargs="+",
        help="Regenerate one or more existing authority entries from their current Wikidata link or from an explicit Wikidata QID/URL, e.g. person_4815 person_4805=Q123.",
    )
    regenerate_parser.set_defaults(handler=run_regenerate)

    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for the ``authorities`` command."""

    parser = build_parser()
    return parser.parse_args(sys.argv[1:] if argv is None else list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    """Run the public CLI and return a process-style exit code."""

    args = parse_args(argv)
    client = WikidataClient(no_fetch=args.no_fetch)
    return args.handler(args, client)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
