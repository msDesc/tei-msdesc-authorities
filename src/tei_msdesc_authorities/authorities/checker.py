"""
Check authority files for duplicate xml:id, Wikidata IDs, and VIAF IDs.
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.parse
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

NS = {
    "tei": "http://www.tei-c.org/ns/1.0",
    "xml": "http://www.w3.org/XML/1998/namespace",
}
BARE_QID_RE = re.compile(r"^Q\d+$", re.IGNORECASE)
WIKIDATA_ENTITY_PATH_RE = re.compile(
    r"^/(?:entity|wiki)/(Q\d+)$", re.IGNORECASE
)
WIKIDATA_ENTITY_DATA_PATH_RE = re.compile(
    r"^/wiki/Special:EntityData/(Q\d+)(?:\.[A-Za-z0-9]+)?$", re.IGNORECASE
)
VIAF_PATH_RE = re.compile(r"^/(?:en/)?viaf/(\d+)(?:/.*)?$", re.IGNORECASE)


@dataclass(slots=True, frozen=True)
class IdentifierIssue:
    """A duplicate identifier problem found in an authority file."""

    authority_path: Path
    identifier_type: str
    identifier_value: str
    keys: tuple[str, ...]
    locations: tuple[tuple[str, int | None], ...]


def parse_xml(path: Path) -> etree._ElementTree:
    """Parse an authority file without discarding source line information."""

    parser = etree.XMLParser(remove_blank_text=False, recover=False)
    return etree.parse(str(path), parser)


def xpath_values(
    node: etree._ElementTree | etree._Element, expression: str
) -> list[object]:
    """Evaluate an XPath expression and always return a list result."""

    result = node.xpath(expression, namespaces=NS)
    return list(result) if isinstance(result, list) else []


def xpath_elements(
    node: etree._ElementTree | etree._Element, expression: str
) -> list[etree._Element]:
    """Return only element nodes from an XPath result."""

    return [
        item
        for item in xpath_values(node, expression)
        if isinstance(item, etree._Element)
    ]


def xpath_strings(
    node: etree._ElementTree | etree._Element, expression: str
) -> list[str]:
    """Return string values from an XPath result."""

    values: list[str] = []
    for item in xpath_values(node, expression):
        if isinstance(item, bytes):
            values.append(item.decode("utf-8", errors="replace"))
        elif isinstance(item, str):
            values.append(item)
    return values


def extract_qid(target: str) -> str | None:
    """Extract a Wikidata QID from a supported target value."""

    value = target.strip()
    if BARE_QID_RE.fullmatch(value):
        return value.upper()
    parsed = urllib.parse.urlparse(value)
    host = parsed.netloc.lower()
    if host not in {"wikidata.org", "www.wikidata.org", "m.wikidata.org"}:
        return None
    match = WIKIDATA_ENTITY_PATH_RE.fullmatch(parsed.path)
    if match:
        return match.group(1).upper()
    match = WIKIDATA_ENTITY_DATA_PATH_RE.fullmatch(parsed.path)
    if match:
        return match.group(1).upper()
    return None


def extract_viaf_id(target: str) -> str | None:
    """Extract a VIAF identifier from a supported target value."""

    parsed = urllib.parse.urlparse(target.strip())
    host = parsed.netloc.lower()
    if host not in {"viaf.org", "www.viaf.org"}:
        return None
    match = VIAF_PATH_RE.fullmatch(parsed.path)
    if match:
        return match.group(1)
    return None


def collect_issues(authority_path: Path) -> list[IdentifierIssue]:
    """Collect duplicate xml:id, Wikidata, and VIAF identifiers in one file."""

    tree = parse_xml(authority_path)
    entries = xpath_elements(
        tree,
        "//tei:person[@xml:id] | //tei:place[@xml:id] | //tei:org[@xml:id] | //tei:bibl[@xml:id]",
    )

    xmlid_to_count: dict[str, int] = defaultdict(int)
    xmlid_to_locations: dict[str, list[tuple[str, int | None]]] = defaultdict(
        list
    )
    qid_to_locations: dict[str, list[tuple[str, int | None]]] = defaultdict(
        list
    )
    viaf_to_locations: dict[str, list[tuple[str, int | None]]] = defaultdict(
        list
    )

    for node in entries:
        key = node.get(f"{{{NS['xml']}}}id")
        if not key:
            continue
        line = node.sourceline if isinstance(node.sourceline, int) else None
        xmlid_to_count[key] += 1
        xmlid_to_locations[key].append((key, line))
        for target_value in xpath_strings(
            node, './/tei:note[@type="links"]//tei:ref/@target'
        ):
            qid = extract_qid(target_value)
            if qid:
                qid_to_locations[qid].append((key, line))
            viaf_id = extract_viaf_id(target_value)
            if viaf_id:
                viaf_to_locations[viaf_id].append((key, line))

    issues: list[IdentifierIssue] = []
    for xmlid, count in sorted(xmlid_to_count.items()):
        if count > 1:
            issues.append(
                IdentifierIssue(
                    authority_path=authority_path,
                    identifier_type="xml:id",
                    identifier_value=xmlid,
                    keys=(xmlid,),
                    locations=tuple(xmlid_to_locations[xmlid]),
                )
            )
    for qid, locations in sorted(qid_to_locations.items()):
        deduped = {(key, line) for key, line in locations}
        keys = tuple(sorted({key for key, _ in deduped}))
        if len(keys) > 1:
            issues.append(
                IdentifierIssue(
                    authority_path=authority_path,
                    identifier_type="Wikidata",
                    identifier_value=qid,
                    keys=keys,
                    locations=tuple(sorted(deduped)),
                )
            )
    for viaf_id, locations in sorted(viaf_to_locations.items()):
        deduped = {(key, line) for key, line in locations}
        keys = tuple(sorted({key for key, _ in deduped}))
        if len(keys) > 1:
            issues.append(
                IdentifierIssue(
                    authority_path=authority_path,
                    identifier_type="VIAF",
                    identifier_value=viaf_id,
                    keys=keys,
                    locations=tuple(sorted(deduped)),
                )
            )
    return issues


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for ``authority-identifiers``."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "authority_files",
        nargs="*",
        type=Path,
        default=[Path("persons.xml"), Path("places.xml"), Path("works.xml")],
        help="Authority files to check. Defaults to persons.xml, places.xml, and works.xml.",
    )
    return parser.parse_args()


def main() -> int:
    """Run the identifier checker and return an exit code."""

    args = parse_args()
    issues: list[IdentifierIssue] = []

    for path in args.authority_files:
        if not path.exists():
            print(f"Missing authority file: {path}", file=sys.stderr)
            return 2
        issues.extend(collect_issues(path))

    if not issues:
        print("No duplicate xml:id, Wikidata, or VIAF identifiers found.")
        return 0

    for issue in issues:
        clickable_locations = ", ".join(
            f"{issue.authority_path}:{line} ({key})"
            if line is not None
            else f"{issue.authority_path} ({key})"
            for key, line in issue.locations
        )
        print(
            f"{issue.authority_path}: duplicate {issue.identifier_type} {issue.identifier_value} in {clickable_locations}",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
