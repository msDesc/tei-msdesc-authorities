"""Core authority workflows and TEI/XML manipulation helpers.

This module contains the domain logic behind the three main CLI workflows:

- enriching manuscript files that contain external ``@ref`` values
- reconciling existing local authority records against Wikidata
- regenerating existing authority entries from their external identifiers

It is intentionally the "thick" module in the package: it owns the project-
specific TEI conventions, identifier routing rules, and manuscript/authority
file update logic.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import textwrap
import unicodedata
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from xml.sax.saxutils import escape

from lxml import etree

from .models import (
    BARE_QID_RE,
    COUNTRY_TYPE_QIDS,
    ID_RE,
    KNOWN_LINK_TITLES,
    LOCAL_AUTHORITY_EQUIVALENTS,
    NS,
    PERSON_ID_LINKS,
    PLACE_ID_LINKS,
    REGION_TYPE_QIDS,
    SETTLEMENT_TYPE_QIDS,
    SEX_MAP,
    SUPPRESSED_LINK_PROPERTIES,
    TRUSTED_PROPERTY_CLASS_QIDS,
    VIAF_PATH_RE,
    WIKIDATA_ENTITY_DATA_PATH_RE,
    WIKIDATA_ENTITY_PATH_RE,
    WORK_ID_LINKS,
    XPATH_CANDIDATES,
    AuthorityListSpec,
    Candidate,
    ClaimStatement,
    ClaimValue,
    CoordinatePoint,
    DuplicateIdentifierIssue,
    ElementName,
    EntityDetails,
    EntityType,
    ExistingPersonEntry,
    ExternalAuthorityIds,
    FloruitRange,
    LinkedAuthorityRef,
    LinkItem,
    NameVariant,
    PersonAuthorityRecord,
    PlannedEntry,
    WorkAuthor,
    element_to_entity,
    entity_to_prefix,
)
from .wikidata import WikidataClient

type EnsureRelatedFn = Callable[[EntityType, str, str], tuple[str, str]]
type EnsurePersonFn = Callable[
    [str | None, str | None, str | None], tuple[str, str, str | None]
]


@dataclass(slots=True)
class AuthorityPaths:
    """The three TEI authority files managed by the workflows."""

    persons: Path
    places: Path
    works: Path

    def for_key(self, key: str) -> tuple[Path, EntityType, str]:
        """Return the authority file and TEI child tag for an existing key."""

        return authority_file_for_key(
            key, self.persons, self.places, self.works
        )


@dataclass(slots=True)
class AuthorityRepository:
    """Repository-style wrapper around the project authority XML files.

    This is intentionally light-weight: it does not replace the existing helper
    functions, but gives the high-level workflows a single object through which
    to load lookup state and apply authority-file updates.
    """

    paths: AuthorityPaths

    def qid_map(self, entity_type: EntityType) -> dict[str, str]:
        """Return the existing local-key map for linked Wikidata QIDs."""

        if entity_type == EntityType.PERSON:
            return read_existing_qid_map(self.paths.persons, entity_type)
        if entity_type in {EntityType.PLACE, EntityType.ORG}:
            return read_existing_qid_map(self.paths.places, entity_type)
        return read_existing_qid_map(self.paths.works, entity_type)

    def display_map(self, entity_type: EntityType) -> dict[str, str]:
        """Return the local display-label map for an authority entity type."""

        if entity_type == EntityType.PERSON:
            return read_person_display_map(self.paths.persons)
        if entity_type in {EntityType.PLACE, EntityType.ORG}:
            return read_entity_display_map(self.paths.places, entity_type)
        return {}

    def used_ids(self) -> dict[str, set[int]]:
        """Return the currently allocated numeric local identifiers."""

        return {
            "person": get_used_ids(
                self.paths.persons, "person", "//tei:person/@xml:id"
            ),
            "place": get_used_ids(
                self.paths.places, "place", "//tei:place/@xml:id"
            ),
            "org": get_used_ids(self.paths.places, "org", "//tei:org/@xml:id"),
            "work": get_used_ids(
                self.paths.works, "work", "//tei:bibl/@xml:id"
            ),
        }

    def insert_entries(
        self,
        list_tag: str,
        list_type: str,
        child_tag: str,
        prefix: str,
        entries: list[PlannedEntry],
    ) -> None:
        """Insert new authority entries into the appropriate authority file."""

        if list_tag == "listPerson":
            authority_path = self.paths.persons
        elif list_tag in {"listPlace", "listOrg"}:
            authority_path = self.paths.places
        else:
            authority_path = self.paths.works
        insert_entries_in_numeric_order(
            authority_path, list_tag, list_type, child_tag, prefix, entries
        )

    def replace_entry(self, key: str, child_tag: str, xml_snippet: str) -> Path:
        """Replace one existing authority record in place and return its file."""

        authority_path, _, _ = self.paths.for_key(key)
        replace_authority_entry_in_place(
            authority_path, key, child_tag, xml_snippet
        )
        return authority_path


@dataclass(slots=True)
class RegenerationState:
    """Shared lookup state reused during multi-entry regeneration runs.

    Regenerating several entries in one invocation can otherwise be slow,
    because the same authority files would be reparsed repeatedly in order to
    rebuild QID maps, display-label maps, and numeric ID allocation state.
    """

    existing_person_qid_map: dict[str, str]
    existing_place_qid_map: dict[str, str]
    existing_org_qid_map: dict[str, str]
    person_display_map: dict[str, str]
    place_display_map: dict[str, str]
    org_display_map: dict[str, str]
    used_ids: dict[str, set[int]]

    @classmethod
    def load(
        cls,
        *,
        persons_path: Path | None = None,
        places_path: Path | None = None,
        works_path: Path | None = None,
        repository: AuthorityRepository | None = None,
    ) -> "RegenerationState":
        if repository is None:
            if (
                persons_path is None
                or places_path is None
                or works_path is None
            ):
                raise ValueError(
                    "RegenerationState.load requires either a repository or all three authority paths"
                )
            repository = AuthorityRepository(
                AuthorityPaths(
                    persons=persons_path,
                    places=places_path,
                    works=works_path,
                )
            )
        return cls(
            existing_person_qid_map=repository.qid_map(EntityType.PERSON),
            existing_place_qid_map=repository.qid_map(EntityType.PLACE),
            existing_org_qid_map=repository.qid_map(EntityType.ORG),
            person_display_map=repository.display_map(EntityType.PERSON),
            place_display_map=repository.display_map(EntityType.PLACE),
            org_display_map=repository.display_map(EntityType.ORG),
            used_ids=repository.used_ids(),
        )

    def record_entry(
        self, entity_type: EntityType, qid: str, key: str, label: str
    ) -> None:
        if entity_type == EntityType.PERSON:
            self.existing_person_qid_map[qid] = key
            self.person_display_map[key] = label
        elif entity_type == EntityType.PLACE:
            self.existing_place_qid_map[qid] = key
            self.place_display_map[key] = label
        elif entity_type == EntityType.ORG:
            self.existing_org_qid_map[qid] = key
            self.org_display_map[key] = label


def parse_xml(path: Path) -> etree._ElementTree:
    """Parse TEI XML without normalizing whitespace.

    Preserving original whitespace is important because the tool aims to make
    narrowly targeted edits rather than reformat whole authority files.
    """

    parser = etree.XMLParser(remove_blank_text=False, recover=False)
    return etree.parse(str(path), parser)


def xpath_values(
    node: etree._ElementTree | etree._Element,
    expression: str,
    *,
    key: str | None = None,
) -> list[object]:
    if key is None:
        result = node.xpath(expression, namespaces=NS)
    else:
        result = node.xpath(expression, namespaces=NS, key=key)
    return list(result) if isinstance(result, list) else []


def xpath_elements(
    node: etree._ElementTree | etree._Element,
    expression: str,
    *,
    key: str | None = None,
) -> list[etree._Element]:
    return [
        item
        for item in xpath_values(node, expression, key=key)
        if isinstance(item, etree._Element)
    ]


def xpath_strings(
    node: etree._ElementTree | etree._Element,
    expression: str,
    *,
    key: str | None = None,
) -> list[str]:
    values: list[str] = []
    for item in xpath_values(node, expression, key=key):
        if isinstance(item, bytes):
            values.append(item.decode("utf-8", errors="replace"))
        elif isinstance(item, str):
            values.append(item)
    return values


def normalize_element_text(node: etree._Element) -> str:
    parts: list[str] = []
    for part in node.itertext():
        if isinstance(part, bytes):
            parts.append(part.decode("utf-8", errors="replace"))
        else:
            parts.append(part)
    return " ".join("".join(parts).split())


def extract_qid(ref: str) -> str | None:
    """Extract a Wikidata QID from a supported ref/target value.

    The parser is intentionally strict: it only accepts bare QIDs and genuine
    Wikidata entity/wiki URLs, not arbitrary URLs that happen to end in digits.
    """

    value = ref.strip()
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


def collect_candidates(xml_paths: list[Path]) -> list[Candidate]:
    """Collect unresolved manuscript references that should become local keys."""

    candidates: list[Candidate] = []
    for xml_path in xml_paths:
        tree = parse_xml(xml_path)
        for node in xpath_elements(tree, XPATH_CANDIDATES):
            local = etree.QName(node.tag).localname
            try:
                element_name = ElementName(local)
            except ValueError:
                continue
            entity_type = element_to_entity(local)
            if entity_type is None:
                continue

            ref = (node.get("ref") or "").strip()
            qid = extract_qid(ref)
            if not qid:
                continue

            text = normalize_element_text(node)
            context_author_key: str | None = None
            context_author_text: str | None = None
            if entity_type == EntityType.WORK:
                msitem = xpath_elements(node, "ancestor::tei:msItem[1]")
                if msitem:
                    msitem_node = msitem[0]
                    author_nodes = xpath_elements(
                        msitem_node, "./tei:author[@key][1]"
                    )
                    if author_nodes:
                        author_node = author_nodes[0]
                        context_author_key = (
                            author_node.get("key") or ""
                        ).strip() or None
                        author_text = normalize_element_text(author_node)
                        context_author_text = author_text or None
            candidates.append(
                Candidate(
                    file_path=xml_path,
                    element_name=element_name,
                    entity_type=entity_type,
                    ref=ref,
                    qid=qid,
                    text=text,
                    context_author_key=context_author_key,
                    context_author_text=context_author_text,
                )
            )
    return candidates


def read_existing_qid_map(
    authority_path: Path, entity_type: EntityType
) -> dict[str, str]:
    """Map linked Wikidata QIDs to existing local authority keys."""

    tree = parse_xml(authority_path)
    if entity_type == EntityType.PERSON:
        entries = xpath_elements(tree, "//tei:person[@xml:id]")
    elif entity_type == EntityType.WORK:
        entries = xpath_elements(tree, "//tei:bibl[@xml:id]")
    elif entity_type == EntityType.PLACE:
        entries = xpath_elements(tree, "//tei:place[@xml:id]")
    else:
        entries = xpath_elements(tree, "//tei:org[@xml:id]")

    mapping: dict[str, str] = {}
    for node in entries:
        xml_id = node.get(f"{{{NS['xml']}}}id")
        if not xml_id:
            continue
        for target in xpath_strings(
            node, './/tei:note[@type="links"]//tei:ref/@target'
        ):
            qid = extract_qid(target)
            if qid:
                mapping[qid] = xml_id
    return mapping


def read_person_display_map(authority_path: Path) -> dict[str, str]:
    tree = parse_xml(authority_path)
    mapping: dict[str, str] = {}
    entries = xpath_elements(tree, "//tei:person[@xml:id]")
    for node in entries:
        xml_id = node.get(f"{{{NS['xml']}}}id")
        if not xml_id:
            continue
        display = xpath_elements(node, './tei:persName[@type="display"][1]')
        if not display:
            continue
        display_node = display[0]
        text = normalize_element_text(display_node)
        if text:
            mapping[xml_id] = text
    return mapping


def read_entity_display_map(
    authority_path: Path, entity_type: EntityType
) -> dict[str, str]:
    tree = parse_xml(authority_path)
    mapping: dict[str, str] = {}
    if entity_type == EntityType.PLACE:
        entries = xpath_elements(tree, "//tei:place[@xml:id]")
        xpath = './tei:placeName[@type="index" or @type="display"][1]'
    elif entity_type == EntityType.ORG:
        entries = xpath_elements(tree, "//tei:org[@xml:id]")
        xpath = './tei:orgName[@type="display"][1]'
    elif entity_type == EntityType.WORK:
        entries = xpath_elements(tree, "//tei:bibl[@xml:id]")
        xpath = './tei:title[@type="uniform"][1]'
    else:
        return read_person_display_map(authority_path)
    for node in entries:
        xml_id = node.get(f"{{{NS['xml']}}}id")
        if not xml_id:
            continue
        display = xpath_elements(node, xpath)
        if not display:
            continue
        display_node = display[0]
        text = normalize_element_text(display_node)
        if text:
            mapping[xml_id] = text
    return mapping


def equivalent_local_key(entity_type: EntityType, qid: str) -> str | None:
    return LOCAL_AUTHORITY_EQUIVALENTS.get((entity_type, qid.upper()))


def extract_viaf_id(target: str) -> str | None:
    parsed = urllib.parse.urlparse(target.strip())
    host = parsed.netloc.lower()
    if host not in {"viaf.org", "www.viaf.org"}:
        return None
    match = VIAF_PATH_RE.fullmatch(parsed.path)
    if match:
        return match.group(1)
    return None


def read_person_authority_records(
    authority_path: Path,
) -> dict[str, PersonAuthorityRecord]:
    tree = parse_xml(authority_path)
    records: dict[str, PersonAuthorityRecord] = {}
    entries = xpath_elements(tree, "//tei:person[@xml:id]")
    for node in entries:
        key = node.get(f"{{{NS['xml']}}}id")
        if not key:
            continue

        display_label: str | None = None
        display = xpath_elements(node, './tei:persName[@type="display"][1]')
        if display:
            display_node = display[0]
            text = normalize_element_text(display_node)
            if text:
                display_label = text

        wikidata_qids: set[str] = set()
        viaf_ids: set[str] = set()
        for target_value in xpath_strings(
            node, './/tei:note[@type="links"]//tei:ref/@target'
        ):
            qid = extract_qid(target_value)
            if qid:
                wikidata_qids.add(qid)
            viaf_id = extract_viaf_id(target_value)
            if viaf_id:
                viaf_ids.add(viaf_id)

        records[key] = PersonAuthorityRecord(
            key=key,
            display_label=display_label,
            wikidata_qids=frozenset(wikidata_qids),
            viaf_ids=frozenset(viaf_ids),
        )
    return records


def strip_display_date_suffix(label: str) -> str:
    text = " ".join(label.split())
    patterns = (
        r",\s*fl\..*$",
        r",\s*active .*$",
        r",\s*approximately .*$",
        r",\s*[0-9?][^,]*$",
        r",\s*[0-9]{1,2}(?:st|nd|rd|th) century.*$",
        r",\s*[A-Za-z -]*century.*$",
        r",\s*-\d.*$",
        r"\s+[–-]\d.*$",
        r"\s+\(\?[^)]*\)$",
    )
    for pattern in patterns:
        stripped = (
            re.sub(pattern, "", text, flags=re.IGNORECASE)
            .strip()
            .rstrip(",")
            .strip()
        )
        if stripped != text:
            return stripped
    return text


def normalize_name_for_match(value: str) -> str:
    lowered = value.casefold()
    lowered = re.sub(r"[^\w\s]", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered.strip()


def parse_existing_person_entries(
    authority_path: Path,
) -> list[ExistingPersonEntry]:
    tree = parse_xml(authority_path)
    entries = xpath_elements(tree, "//tei:person[@xml:id]")
    parsed: list[ExistingPersonEntry] = []
    for node in entries:
        key = node.get(f"{{{NS['xml']}}}id")
        if not key:
            continue
        display_nodes = xpath_elements(
            node, './tei:persName[@type="display"][1]'
        )
        if not display_nodes:
            continue
        display_node = display_nodes[0]
        display_label = normalize_element_text(display_node)
        if not display_label:
            continue
        wikidata_qids: set[str] = set()
        viaf_ids: set[str] = set()
        for target_value in xpath_strings(
            node, './/tei:note[@type="links"]//tei:ref/@target'
        ):
            qid = extract_qid(target_value)
            if qid:
                wikidata_qids.add(qid)
            viaf_id = extract_viaf_id(target_value)
            if viaf_id:
                viaf_ids.add(viaf_id)
        birth = xpath_strings(node, "./tei:birth/@when")
        death = xpath_strings(node, "./tei:death/@when")
        floruit_nodes = xpath_elements(node, "./tei:floruit[1]")
        floruit: FloruitRange | None = None
        if floruit_nodes:
            floruit_node = floruit_nodes[0]
            floruit = FloruitRange(
                from_value=floruit_node.get("from")
                or floruit_node.get("notBefore"),
                to_value=floruit_node.get("to") or floruit_node.get("notAfter"),
            )
        parsed.append(
            ExistingPersonEntry(
                key=key,
                line=node.sourceline
                if isinstance(node.sourceline, int)
                else None,
                display_label=display_label,
                query_label=strip_display_date_suffix(display_label),
                wikidata_qids=frozenset(wikidata_qids),
                viaf_ids=frozenset(viaf_ids),
                birth=birth[0] if birth else None,
                death=death[0] if death else None,
                floruit=floruit,
            )
        )
    return parsed


def extract_year(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"-?(\d{3,4})", value)
    if match:
        return match.group(1)
    return None


def reconciliation_queries_for_person(entry: ExistingPersonEntry) -> list[str]:
    queries: list[str] = []
    base = entry.query_label.strip()
    if not base:
        return queries

    death_year = extract_year(entry.death) or extract_year(entry.display_label)
    birth_year = extract_year(entry.birth)

    if death_year:
        queries.append(f"{base} {death_year}")
    if birth_year and birth_year != death_year:
        queries.append(f"{base} {birth_year}")
    queries.append(base)

    deduped: list[str] = []
    seen: set[str] = set()
    for query in queries:
        normalized = " ".join(query.split())
        if normalized and normalized not in seen:
            deduped.append(normalized)
            seen.add(normalized)
    return deduped


def reconciliation_query_bonus(
    search_query: str, entry: ExistingPersonEntry
) -> tuple[float, str | None]:
    death_year = extract_year(entry.death) or extract_year(entry.display_label)
    birth_year = extract_year(entry.birth)
    if death_year and search_query.endswith(f" {death_year}"):
        return 0.05, f"retrieved by name+death-year query ({death_year})"
    if birth_year and search_query.endswith(f" {birth_year}"):
        return 0.04, f"retrieved by name+birth-year query ({birth_year})"
    return 0.0, None


def score_person_reconciliation(
    entry: ExistingPersonEntry,
    details: EntityDetails,
    entity: dict[str, object] | None,
) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0

    local_name = normalize_name_for_match(entry.query_label)
    candidate_name = normalize_name_for_match(display_label_for_person(details))
    if local_name and local_name == candidate_name:
        score += 0.6
        reasons.append("exact normalized name match")
    elif local_name and any(
        normalize_name_for_match(variant.value) == local_name
        for variant in details.variants
    ):
        score += 0.45
        reasons.append("name matches Wikidata variant")

    candidate_viaf = first_numeric_identifier(entity, "P214")
    if candidate_viaf and candidate_viaf in entry.viaf_ids:
        score += 0.3
        reasons.append("VIAF match")

    local_death = extract_year(entry.death) or extract_year(entry.display_label)
    candidate_death = extract_year(details.death)
    if local_death and candidate_death and local_death == candidate_death:
        score += 0.2
        reasons.append(f"death date matches {local_death}")

    local_birth = extract_year(entry.birth)
    candidate_birth = extract_year(details.birth)
    if local_birth and candidate_birth and local_birth == candidate_birth:
        score += 0.2
        reasons.append(f"birth date matches {local_birth}")

    if (
        entry.floruit
        and details.floruit
        and entry.floruit.from_value
        and details.floruit.from_value
    ):
        local_from = extract_year(entry.floruit.from_value)
        candidate_from = extract_year(details.floruit.from_value)
        if local_from and candidate_from and local_from == candidate_from:
            score += 0.15
            reasons.append(f"floruit start matches {local_from}")

    return min(score, 1.0), reasons


def reconcile_existing_persons(
    authority_path: Path, client: WikidataClient, limit: int
) -> list[dict[str, object]]:
    reconciliations: list[dict[str, object]] = []
    for entry in parse_existing_person_entries(authority_path):
        if entry.wikidata_qids:
            continue
        candidates_by_qid: dict[str, dict[str, object]] = {}
        search_queries = reconciliation_queries_for_person(entry)
        for search_query in search_queries:
            search_results = client.search_entities(search_query, limit=limit)
            search_qids = [
                qid
                for search_result in search_results
                if isinstance((qid := search_result.get("id")), str)
                and qid.startswith("Q")
            ]
            client.get_entities(search_qids)
            for search_result in search_results:
                qid = search_result.get("id")
                if not isinstance(qid, str) or not qid.startswith("Q"):
                    continue
                entity = client.get_entity(qid)
                details = build_person_details(
                    qid, str(search_result.get("label") or qid), client
                )
                score, reasons = score_person_reconciliation(
                    entry, details, entity
                )
                query_bonus, query_reason = reconciliation_query_bonus(
                    search_query, entry
                )
                score += query_bonus
                if query_reason:
                    reasons = [*reasons, query_reason]
                if score <= 0:
                    continue
                candidate: dict[str, object] = {
                    "qid": qid,
                    "label": display_label_for_person(details),
                    "description": str(search_result.get("description") or ""),
                    "score": round(score, 2),
                    "decision": "suggest" if score >= 0.75 else "ambiguous",
                    "approved": False,
                    "reasons": reasons,
                    "matched_by_query": search_query,
                    "external_ids": {
                        "viaf": details.external_ids.viaf,
                    },
                }
                existing_candidate = candidates_by_qid.get(qid)
                candidate_score = cast(float, candidate["score"])
                existing_score = (
                    cast(float, existing_candidate["score"])
                    if existing_candidate is not None
                    else -math.inf
                )
                if (
                    existing_candidate is None
                    or candidate_score > existing_score
                ):
                    candidates_by_qid[qid] = candidate
        candidates = list(candidates_by_qid.values())
        candidates.sort(
            key=lambda candidate: (
                -cast(float, candidate["score"]),
                str(candidate["qid"]),
            )
        )
        reconciliations.append(
            {
                "entity_type": "person",
                "key": entry.key,
                "line": entry.line,
                "display_label": entry.display_label,
                "query_label": entry.query_label,
                "search_queries": search_queries,
                "existing_ids": {
                    "wikidata": sorted(entry.wikidata_qids),
                    "viaf": sorted(entry.viaf_ids),
                },
                "candidates": candidates[:limit],
            }
        )
    return reconciliations


def approved_reconciliations_from_report(report_path: Path) -> dict[str, str]:
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ValueError(f"Invalid reconciliation report format: {report_path}")

    approved: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entity_type = entry.get("entity_type")
        if entity_type != "person":
            continue
        key = entry.get("key")
        if not isinstance(key, str) or not key:
            continue
        candidates = entry.get("candidates")
        if not isinstance(candidates, list):
            continue
        approved_candidates = [
            candidate
            for candidate in candidates
            if isinstance(candidate, dict)
            and candidate.get("approved") is True
            and isinstance(candidate.get("qid"), str)
        ]
        if len(approved_candidates) > 1:
            raise ValueError(
                f"Multiple approved candidates found for {key} in {report_path}"
            )
        if approved_candidates:
            approved[key] = str(approved_candidates[0]["qid"])
    return approved


def append_wikidata_link_item(person_node: etree._Element, qid: str) -> None:
    target = f"https://www.wikidata.org/entity/{qid}"
    notes = xpath_elements(person_node, './tei:note[@type="links"][1]')
    if notes:
        note = notes[0]
        lists = xpath_elements(note, "./tei:list[1]")
        if lists:
            links_list = lists[0]
        else:
            links_list = etree.SubElement(note, f"{{{NS['tei']}}}list")
            links_list.set("type", "links")
            links_list.text = "\n                     "
            links_list.tail = "\n               "
    else:
        note = etree.Element(f"{{{NS['tei']}}}note")
        note.set("type", "links")
        links_list = etree.SubElement(note, f"{{{NS['tei']}}}list")
        links_list.set("type", "links")

    child_indent = (
        person_node.text
        if person_node.text and "\n" in person_node.text
        else "\n               "
    )
    closing_indent = (
        person_node[-1].tail
        if len(person_node)
        and person_node[-1].tail
        and "\n" in person_node[-1].tail
        else "\n            "
    )

    if note.getparent() is None:
        if len(person_node):
            person_node[-1].tail = child_indent
        else:
            person_node.text = child_indent
        note.text = "\n                  "
        note.tail = closing_indent
        links_list.text = "\n                     "
        links_list.tail = "\n               "
        person_node.append(note)

    item_indent = (
        links_list.text
        if links_list.text and "\n" in links_list.text
        else "\n                     "
    )
    list_closing_indent = (
        links_list[-1].tail
        if len(links_list)
        and links_list[-1].tail
        and "\n" in links_list[-1].tail
        else "\n                  "
    )

    item = etree.Element(f"{{{NS['tei']}}}item")
    item.text = "\n                        "
    item.tail = list_closing_indent
    ref = etree.SubElement(item, f"{{{NS['tei']}}}ref")
    ref.set("target", target)
    ref.text = "\n                           "
    ref.tail = "\n                     "
    title = etree.SubElement(ref, f"{{{NS['tei']}}}title")
    title.text = "Wikidata"
    title.tail = "\n                        "

    if len(links_list):
        links_list[-1].tail = item_indent
    else:
        links_list.text = item_indent
    links_list.append(item)


def apply_approved_person_reconciliations(
    persons_path: Path, approved: dict[str, str]
) -> int:
    if not approved:
        return 0

    original_text = persons_path.read_text(encoding="utf-8")
    tree = parse_xml(persons_path)
    changed = 0
    entries = xpath_elements(tree, "//tei:person[@xml:id]")
    for node in entries:
        key = node.get(f"{{{NS['xml']}}}id")
        if not key or key not in approved:
            continue
        qid = approved[key]
        target = f"https://www.wikidata.org/entity/{qid}"
        existing_targets = set(
            xpath_strings(node, './/tei:note[@type="links"]//tei:ref/@target')
        )
        if target in existing_targets:
            continue

        append_wikidata_link_item(node, qid)
        changed += 1

    if changed:
        write_preserving_header(tree, persons_path, original_text)
    return changed


def parse_regenerate_spec(spec: str) -> tuple[str, str | None]:
    spec = spec.strip()
    if "=" not in spec:
        if not spec:
            raise ValueError(
                "Invalid regenerate spec ''; expected KEY or KEY=QID/URL"
            )
        return spec, None
    key, ref = spec.split("=", 1)
    key = key.strip()
    ref = ref.strip()
    qid = extract_qid(ref)
    if not key or not qid:
        raise ValueError(
            f"Invalid regenerate spec '{spec}'; could not parse key and Wikidata QID"
        )
    return key, qid


def authority_file_for_key(
    key: str, persons_path: Path, places_path: Path, works_path: Path
) -> tuple[Path, EntityType, str]:
    if key.startswith("person_"):
        return persons_path, EntityType.PERSON, "person"
    if key.startswith("place_"):
        return places_path, EntityType.PLACE, "place"
    if key.startswith("org_"):
        return places_path, EntityType.ORG, "org"
    if key.startswith("work_"):
        return works_path, EntityType.WORK, "bibl"
    raise ValueError(f"Unsupported authority key: {key}")


def existing_entry_fallback_text(
    authority_path: Path, key: str, child_tag: str
) -> str:
    tree = parse_xml(authority_path)
    entries = xpath_elements(tree, f"//tei:{child_tag}[@xml:id=$key]", key=key)
    if not entries:
        raise ValueError(f"Could not find {key} in {authority_path}")
    node = entries[0]
    if child_tag == "person":
        display = xpath_elements(node, './tei:persName[@type="display"][1]')
    elif child_tag == "place":
        display = xpath_elements(
            node, './tei:placeName[@type="index" or @type="display"][1]'
        )
    elif child_tag == "org":
        display = xpath_elements(node, './tei:orgName[@type="display"][1]')
    else:
        display = xpath_elements(node, './tei:title[@type="uniform"][1]')
    if display:
        display_node = display[0]
        text = normalize_element_text(display_node)
        if text:
            return text
    return key


def existing_entry_wikidata_qid(
    authority_path: Path, key: str, child_tag: str
) -> str | None:
    tree = parse_xml(authority_path)
    entries = xpath_elements(tree, f"//tei:{child_tag}[@xml:id=$key]", key=key)
    if not entries:
        raise ValueError(f"Could not find {key} in {authority_path}")
    node = entries[0]
    for target in xpath_strings(
        node, './/tei:note[@type="links"]//tei:ref/@target'
    ):
        qid = extract_qid(target)
        if qid:
            return qid
    return None


def replace_authority_entry_in_place(
    authority_path: Path, key: str, child_tag: str, xml_snippet: str
) -> None:
    source = authority_path.read_text(encoding="utf-8")
    marker = re.search(rf'xml:id=["\']{re.escape(key)}["\']', source)
    if marker is None:
        raise ValueError(f"Could not find entry {key} in {authority_path}")
    tag_start = source.rfind(f"<{child_tag}", 0, marker.start())
    start = source.rfind("\n", 0, tag_start)
    start = 0 if start == -1 else start + 1
    end = source.find(f"</{child_tag}>", marker.end())
    if tag_start == -1 or end == -1:
        raise ValueError(
            f"Located {key} in {authority_path}, but could not determine the surrounding <{child_tag}> element for replacement"
        )
    end += len(f"</{child_tag}>")
    indent = leading_indent_before(source, tag_start)
    replacement = re.sub(r"^ {12}", indent, xml_snippet, flags=re.MULTILINE)
    updated = source[:start] + replacement + source[end:]
    authority_path.write_text(updated, encoding="utf-8")


def regenerate_entry(
    key: str,
    qid: str,
    *,
    persons_path: Path,
    places_path: Path,
    works_path: Path,
    client: WikidataClient,
    min_ids: dict[str, int],
    regeneration_state: RegenerationState | None = None,
) -> tuple[Path, EntityType, tuple[PlannedEntry, ...]]:
    """Regenerate one existing authority entry while preserving its local key."""
    repository = AuthorityRepository(
        AuthorityPaths(
            persons=persons_path, places=places_path, works=works_path
        )
    )
    authority_path, entity_type, child_tag = repository.paths.for_key(key)
    fallback_text = existing_entry_fallback_text(authority_path, key, child_tag)
    if client.get_entity(qid) is None:
        reason = (
            client.last_error or "failed to fetch live Wikidata entity data"
        )
        raise ValueError(
            f"Cannot regenerate {key} from {qid}: {reason}. "
            "No changes were written."
        )

    state = regeneration_state or RegenerationState.load(repository=repository)
    existing_person_qid_map = state.existing_person_qid_map
    existing_place_qid_map = state.existing_place_qid_map
    existing_org_qid_map = state.existing_org_qid_map
    person_display_map = state.person_display_map
    place_display_map = state.place_display_map
    org_display_map = state.org_display_map
    used_ids = state.used_ids
    planned_related: dict[tuple[EntityType, str], PlannedEntry] = {}

    def ensure_person_for_work(
        author_qid: str | None,
        preferred_key: str | None = None,
        preferred_text: str | None = None,
    ) -> tuple[str, str, str | None]:
        if author_qid is None:
            if not preferred_key:
                raise ValueError(
                    "preferred_key is required when no author_qid is supplied"
                )
            return (
                preferred_key,
                person_display_map.get(
                    preferred_key, preferred_text or preferred_key
                ),
                None,
            )
        existing_key = existing_person_qid_map.get(author_qid)
        if existing_key:
            return (
                existing_key,
                person_display_map.get(existing_key, author_qid),
                None,
            )
        raise ValueError(
            f"Cannot regenerate work entry from {qid}: author {author_qid} is not present in persons.xml"
        )

    def ensure_related_for_person(
        entity_type: EntityType, related_qid: str, fallback_label: str
    ) -> tuple[str, str]:
        equivalent_key = equivalent_local_key(entity_type, related_qid)
        if equivalent_key is not None:
            if entity_type == "place":
                return equivalent_key, place_display_map.get(
                    equivalent_key, fallback_label
                )
            if entity_type == "org":
                return equivalent_key, org_display_map.get(
                    equivalent_key, fallback_label
                )
        if entity_type == "place":
            existing_key = existing_place_qid_map.get(related_qid)
            if existing_key:
                return existing_key, place_display_map.get(
                    existing_key, fallback_label
                )
        elif entity_type == "org":
            existing_key = existing_org_qid_map.get(related_qid)
            if existing_key:
                return existing_key, org_display_map.get(
                    existing_key, fallback_label
                )
        else:
            raise ValueError(
                f"Unsupported related entity type for person regeneration: {entity_type}"
            )

        target = (entity_type, related_qid)
        if target in planned_related:
            planned_entry = planned_related[target]
            return planned_entry.key, planned_entry.label

        if entity_type == "place":
            details = build_place_details(
                related_qid, fallback_label or related_qid, client
            )
            planned_label_map = place_display_map
        else:
            details = build_org_details(
                related_qid, fallback_label or related_qid, client
            )
            planned_label_map = org_display_map

        new_key = assign_key_for_details(
            details, entity_type, used_ids, min_ids
        )
        snippet = (
            build_place_snippet(new_key, details)
            if entity_type == "place"
            else build_org_snippet(new_key, details)
        )
        list_spec = route_entity(details, entity_type)
        planned_related[target] = PlannedEntry(
            qid=related_qid,
            key=new_key,
            entity_type=entity_type,
            label=details.label,
            list_spec=list_spec,
            external_ids=details.external_ids,
            xml_snippet=snippet,
        )
        planned_label_map[new_key] = details.label
        return new_key, details.label

    if entity_type == "person":
        details = build_person_details(
            qid, fallback_text, client, ensure_related_for_person
        )
        snippet = build_person_snippet(key, details)
    elif entity_type == "place":
        details = build_place_details(qid, fallback_text, client)
        snippet = build_place_snippet(key, details)
    elif entity_type == "org":
        details = build_org_details(qid, fallback_text, client)
        snippet = build_org_snippet(key, details)
    else:
        details = build_work_details(
            qid, fallback_text, client, ensure_person_for_work
        )
        snippet = build_work_snippet(key, details)

    if planned_related:
        entries_by_list: dict[
            tuple[str, str, str, str], list[PlannedEntry]
        ] = {}
        for (_, _), entry in sorted(planned_related.items()):
            spec = entry.list_spec
            entries_by_list.setdefault(
                (spec.list_tag, spec.list_type, spec.child_tag, spec.prefix), []
            ).append(entry)
        for (
            list_tag,
            list_type,
            list_child_tag,
            prefix,
        ), entries in entries_by_list.items():
            repository.insert_entries(
                list_tag, list_type, list_child_tag, prefix, entries
            )
        for (_, _), entry in sorted(planned_related.items()):
            state.record_entry(
                entry.entity_type, entry.qid, entry.key, entry.label
            )

    repository.replace_entry(key, child_tag, snippet)
    state.record_entry(entity_type, qid, key, details.label)
    created_related = tuple(
        entry for (_, _), entry in sorted(planned_related.items())
    )
    return authority_path, entity_type, created_related


def collect_duplicate_identifier_issues(
    authority_path: Path,
) -> list[DuplicateIdentifierIssue]:
    tree = parse_xml(authority_path)
    entries = xpath_elements(
        tree,
        "//tei:person[@xml:id] | //tei:place[@xml:id] | //tei:org[@xml:id] | //tei:bibl[@xml:id]",
    )

    qid_to_locations: dict[str, list[tuple[str, int | None]]] = {}
    viaf_to_locations: dict[str, list[tuple[str, int | None]]] = {}

    for node in entries:
        key = node.get(f"{{{NS['xml']}}}id")
        if not key:
            continue
        line = node.sourceline if isinstance(node.sourceline, int) else None
        for target_value in xpath_strings(
            node, './/tei:note[@type="links"]//tei:ref/@target'
        ):
            qid = extract_qid(target_value)
            if qid:
                qid_to_locations.setdefault(qid, []).append((key, line))
            viaf_id = extract_viaf_id(target_value)
            if viaf_id:
                viaf_to_locations.setdefault(viaf_id, []).append((key, line))

    issues: list[DuplicateIdentifierIssue] = []
    for qid, locations in sorted(qid_to_locations.items()):
        deduped = {(key, line) for key, line in locations}
        keys = tuple(sorted({key for key, _ in deduped}))
        if len(keys) > 1:
            issues.append(
                DuplicateIdentifierIssue(
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
                DuplicateIdentifierIssue(
                    authority_path=authority_path,
                    identifier_type="VIAF",
                    identifier_value=viaf_id,
                    keys=keys,
                    locations=tuple(sorted(deduped)),
                )
            )
    return issues


def ensure_unique_authority_identifiers(authority_paths: list[Path]) -> None:
    issues: list[DuplicateIdentifierIssue] = []
    for path in authority_paths:
        issues.extend(collect_duplicate_identifier_issues(path))
    if not issues:
        return

    lines = ["Duplicate external identifiers found in authority files:"]
    for issue in issues:
        clickable_locations = ", ".join(
            f"{issue.authority_path}:{line} ({key})"
            if line is not None
            else f"{issue.authority_path} ({key})"
            for key, line in issue.locations
        )
        lines.append(
            f"- {issue.authority_path}: duplicate {issue.identifier_type} {issue.identifier_value} in {clickable_locations}"
        )
    raise ValueError("\n".join(lines))


def get_used_ids(
    authority_path: Path, prefix: str, xpath_expr: str
) -> set[int]:
    tree = parse_xml(authority_path)
    values = xpath_strings(tree, xpath_expr)
    used: set[int] = set()
    for raw in values:
        m = ID_RE.match(raw)
        if m and m.group(1) == prefix:
            used.add(int(m.group(2)))
    return used


def next_available_id(used: set[int], min_id: int) -> int:
    n = max(1, min_id)
    while n in used:
        n += 1
    used.add(n)
    return n


def get_claim_values(
    entity: dict[str, object], pid: str
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for claim_value in get_claim_value_objects(entity, pid):
        mapping = claim_value.as_mapping()
        if mapping is not None:
            result.append(mapping)
            continue
        string_value = claim_value.as_string()
        if string_value is not None:
            result.append({"string": string_value})
    return result


def get_claim_value_objects(
    entity: dict[str, object] | None, pid: str
) -> tuple[ClaimValue, ...]:
    return tuple(
        statement.mainsnak_value
        for statement in get_claim_statement_objects(entity, pid)
        if statement.mainsnak_value is not None
    )


def get_claim_statements(
    entity: dict[str, object] | None, pid: str
) -> list[dict[str, object]]:
    if not entity:
        return []
    claims = entity.get("claims")
    if not isinstance(claims, dict):
        return []
    items = claims.get(pid)
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def get_claim_statement_objects(
    entity: dict[str, object] | None, pid: str
) -> tuple[ClaimStatement, ...]:
    statements: list[ClaimStatement] = []
    for statement in get_claim_statements(entity, pid):
        mainsnak = statement.get("mainsnak")
        mainsnak_value: ClaimValue | None = None
        if isinstance(mainsnak, dict):
            datavalue = mainsnak.get("datavalue")
            if isinstance(datavalue, dict) and "value" in datavalue:
                mainsnak_value = ClaimValue(datavalue.get("value"))

        qualifiers_map: dict[str, tuple[ClaimValue, ...]] = {}
        qualifiers = statement.get("qualifiers")
        if isinstance(qualifiers, dict):
            for qualifier_pid, qualifier_values in qualifiers.items():
                if not isinstance(qualifier_pid, str) or not isinstance(
                    qualifier_values, list
                ):
                    continue
                extracted: list[ClaimValue] = []
                for qualifier in qualifier_values:
                    if not isinstance(qualifier, dict):
                        continue
                    datavalue = qualifier.get("datavalue")
                    if isinstance(datavalue, dict) and "value" in datavalue:
                        extracted.append(ClaimValue(datavalue.get("value")))
                if extracted:
                    qualifiers_map[qualifier_pid] = tuple(extracted)

        statements.append(
            ClaimStatement(
                mainsnak_value=mainsnak_value, qualifiers=qualifiers_map
            )
        )
    return tuple(statements)


def statement_qualifier_entity_qids(
    statement: dict[str, object], pid: str
) -> list[str]:
    statement_objects = get_claim_statement_objects(
        {"claims": {"_": [statement]}}, "_"
    )
    if not statement_objects:
        return []
    return list(statement_objects[0].qualifier_entity_ids(pid))


def statement_has_uncertain_date_qualifier(
    statement: dict[str, object], client: WikidataClient
) -> bool:
    for qid in statement_qualifier_entity_qids(statement, "P1480"):
        label = preferred_label(client.get_entity(qid), qid).value.casefold()
        if "circa" in label or label.startswith("approx"):
            return True
    return False


def preferred_label(
    entity: dict[str, object] | None, fallback: str
) -> NameVariant:
    if not entity:
        return NameVariant(fallback, None)
    labels = entity.get("labels")
    if not isinstance(labels, dict):
        return NameVariant(fallback, None)
    for key in ("en", "la", "mul"):
        node = labels.get(key)
        if isinstance(node, dict):
            value = node.get("value")
            if isinstance(value, str) and value.strip():
                return NameVariant(value.strip(), key)
    for lang, node in labels.items():
        if isinstance(node, dict):
            value = node.get("value")
            if isinstance(value, str) and value.strip():
                return NameVariant(value.strip(), lang)
    return NameVariant(fallback, None)


def collect_variants(
    entity: dict[str, object] | None,
    display: NameVariant,
    *,
    max_count: int = 6,
) -> tuple[NameVariant, ...]:
    if not entity:
        return ()

    variants: list[NameVariant] = []
    seen_pairs = {(display.value, display.lang)}
    seen_values = {display.value}

    labels = entity.get("labels")
    if isinstance(labels, dict):
        for lang, node in labels.items():
            if not isinstance(node, dict):
                continue
            value = node.get("value")
            if isinstance(value, str) and value.strip():
                candidate = NameVariant(value.strip(), lang)
                if (
                    candidate.value,
                    candidate.lang,
                ) not in seen_pairs and candidate.value not in seen_values:
                    variants.append(candidate)
                    seen_pairs.add((candidate.value, candidate.lang))
                    seen_values.add(candidate.value)

    aliases_node = entity.get("aliases")
    if isinstance(aliases_node, dict):
        for lang, items in aliases_node.items():
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                value = item.get("value")
                if isinstance(value, str) and value.strip():
                    candidate = NameVariant(value.strip(), lang)
                    if (
                        candidate.value,
                        candidate.lang,
                    ) not in seen_pairs and candidate.value not in seen_values:
                        variants.append(candidate)
                        seen_pairs.add((candidate.value, candidate.lang))
                        seen_values.add(candidate.value)
                        if len(variants) >= max_count:
                            return tuple(variants)

    return tuple(variants[:max_count])


def parse_wikidata_time_bounds(
    value: dict[str, object],
) -> tuple[str, str, int] | None:
    raw = value.get("time")
    precision = value.get("precision")
    if not isinstance(raw, str):
        return None
    match = re.match(r"^([+-])(\d{1,16})-(\d{2})-(\d{2})T", raw)
    if not match:
        return None

    sign = "-" if match.group(1) == "-" else ""
    year = (match.group(2).lstrip("0") or "0").zfill(4)
    month = match.group(3)
    day = match.group(4)

    if isinstance(precision, int):
        if precision >= 11 and month != "00" and day != "00":
            exact = f"{sign}{year}-{month}-{day}"
            return exact, exact, precision
        if precision >= 10 and month != "00":
            exact = f"{sign}{year}-{month}"
            return exact, exact, precision
        if precision >= 9:
            exact = f"{sign}{year}"
            return exact, exact, precision
        if precision == 8:
            start = f"{sign}{year}"
            end = f"{sign}{str(int(year) + 9).zfill(4)}"
            return start, end, precision
        if precision == 7:
            start = f"{sign}{year}"
            end = f"{sign}{str(int(year) + 99).zfill(4)}"
            return start, end, precision
    exact = f"{sign}{year}"
    return exact, exact, 9


def first_time(
    entity: dict[str, object] | None, pid: str, *, min_precision: int = 9
) -> str | None:
    if not entity:
        return None
    for value in get_claim_values(entity, pid):
        parsed = parse_wikidata_time_bounds(value)
        if parsed and parsed[2] >= min_precision:
            return parsed[0]
    return None


def first_time_with_circumstances(
    entity: dict[str, object] | None,
    pid: str,
    client: WikidataClient,
    *,
    min_precision: int = 9,
) -> tuple[str | None, bool]:
    if not entity:
        return None, False
    for statement in get_claim_statement_objects(entity, pid):
        value = (
            statement.mainsnak_value.as_mapping()
            if statement.mainsnak_value
            else None
        )
        if not value:
            continue
        parsed = parse_wikidata_time_bounds(value)
        if parsed and parsed[2] >= min_precision:
            uncertain = any(
                (
                    "circa"
                    in preferred_label(
                        client.get_entity(qid), qid
                    ).value.casefold()
                    or preferred_label(client.get_entity(qid), qid)
                    .value.casefold()
                    .startswith("approx")
                )
                for qid in statement.qualifier_entity_ids("P1480")
            )
            return parsed[0], uncertain
    return None, False


def first_time_bounds(
    entity: dict[str, object] | None, pid: str
) -> tuple[str, str, int] | None:
    if not entity:
        return None
    for value in get_claim_values(entity, pid):
        parsed = parse_wikidata_time_bounds(value)
        if parsed:
            return parsed
    return None


def format_precision_date(value: str, precision: int | None) -> str:
    if precision is None:
        return value
    if precision >= 9:
        return value
    try:
        year = int(value[:4])
    except ValueError:
        return value
    if precision == 8:
        decade = (year // 10) * 10
        return f"{decade}s"
    if precision == 7:
        century = (year - 1) // 100 + 1
        suffix = "th"
        if century % 100 not in {11, 12, 13}:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(century % 10, "th")
        return f"{century}{suffix} century"
    return value


def claim_string_values(
    entity: dict[str, object] | None, pid: str
) -> list[str]:
    if not entity:
        return []
    values: list[str] = []
    for claim_value in get_claim_value_objects(entity, pid):
        string_value = claim_value.as_string()
        if string_value is not None:
            values.append(string_value)
    return values


def first_monolingual_text(
    entity: dict[str, object] | None, pid: str
) -> tuple[str, str | None] | None:
    if not entity:
        return None
    for claim_value in get_claim_value_objects(entity, pid):
        monolingual = claim_value.monolingual_text()
        if monolingual is not None:
            return monolingual
    return None


def first_numeric_identifier(
    entity: dict[str, object] | None, pid: str
) -> str | None:
    for value in claim_string_values(entity, pid):
        normalized = re.sub(r"\D", "", value)
        if normalized:
            return normalized
    return None


def first_formatter_url(
    property_entity: dict[str, object] | None,
) -> str | None:
    if not property_entity:
        return None
    for pid in ("P1630", "P3303"):
        values = claim_string_values(property_entity, pid)
        if values:
            return values[0]
    return None


def property_label(pid: str, client: WikidataClient) -> str:
    if pid in KNOWN_LINK_TITLES:
        return KNOWN_LINK_TITLES[pid]
    entity = client.get_entity(pid)
    label = preferred_label(entity, pid).value
    if label.startswith("Mirabile "):
        return "Mirabile"
    if label.endswith(" ID"):
        return label[:-3]
    return label


def property_is_trusted_link_source(
    pid: str, property_entity: dict[str, object] | None
) -> bool:
    if pid in KNOWN_LINK_TITLES:
        return True
    if not property_entity:
        return False
    property_classes = set(claim_entity_qids(property_entity, "P31")) | set(
        claim_entity_qids(property_entity, "P279")
    )
    return bool(property_classes & TRUSTED_PROPERTY_CLASS_QIDS)


def external_id_links(
    entity: dict[str, object] | None,
    client: WikidataClient,
    *,
    excluded_pids: set[str] | None = None,
) -> tuple[LinkItem, ...]:
    if not entity:
        return ()

    claims = entity.get("claims")
    if not isinstance(claims, dict):
        return ()

    excluded = excluded_pids or set()
    links: list[LinkItem] = []
    seen: set[str] = set()
    property_ids = [
        pid
        for pid, claim_list in claims.items()
        if isinstance(pid, str) and isinstance(claim_list, list)
    ]
    property_entities = client.get_entities(property_ids)

    for pid, claim_list in claims.items():
        if not isinstance(pid, str) or not isinstance(claim_list, list):
            continue
        if pid in excluded:
            continue
        if pid in SUPPRESSED_LINK_PROPERTIES:
            continue
        property_entity = property_entities.get(pid)
        if not property_is_trusted_link_source(pid, property_entity):
            continue
        formatter_url = first_formatter_url(property_entity)
        title = property_label(pid, client)

        for claim in claim_list:
            if not isinstance(claim, dict):
                continue
            mainsnak = claim.get("mainsnak")
            if not isinstance(mainsnak, dict):
                continue
            datatype = mainsnak.get("datatype")
            datavalue = mainsnak.get("datavalue")
            if not isinstance(datavalue, dict):
                continue
            value = datavalue.get("value")

            if datatype == "url" and isinstance(value, str):
                if value not in seen:
                    links.append(LinkItem(title=title, target=value))
                    seen.add(value)
                continue

            if (
                datatype == "external-id"
                and isinstance(value, str)
                and formatter_url
            ):
                target = formatter_url.replace(
                    "$1", urllib.parse.quote(value, safe="")
                )
                if target not in seen:
                    links.append(LinkItem(title=title, target=target))
                    seen.add(target)

    return tuple(links)


def sex_from_entity(entity: dict[str, object] | None) -> str | None:
    qids = claim_entity_qids(entity, "P21")
    for qid in qids:
        mapped = SEX_MAP.get(qid)
        if mapped:
            return mapped
    return None


def floruit_from_entity(
    entity: dict[str, object] | None,
) -> FloruitRange | None:
    start = first_time_bounds(entity, "P2031")
    end = first_time_bounds(entity, "P2032")
    if start is None and end is None:
        return None
    from_value = start[0] if start is not None else None
    to_value = end[1] if end is not None else None
    return FloruitRange(
        from_value=from_value,
        to_value=to_value,
        from_precision=start[2] if start is not None else None,
        to_precision=end[2] if end is not None else None,
    )


def floruit_certainty(floruit: FloruitRange | None) -> str | None:
    if floruit is None:
        return None
    precisions = [
        precision
        for precision in (floruit.from_precision, floruit.to_precision)
        if isinstance(precision, int)
    ]
    if not precisions:
        return None
    lowest_precision = min(precisions)
    if lowest_precision < 9:
        return "low"
    return None


def display_date_suffix(details: EntityDetails) -> str | None:
    def format_display_life_date(value: str) -> str:
        if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
            return value[:4]
        return format_precision_date(
            value, 9 if re.match(r"^\d{4}$", value) else None
        )

    def qualify(value: str, uncertain: bool) -> str:
        rendered = format_display_life_date(value)
        return f"{rendered}?" if uncertain else rendered

    if details.birth and details.death:
        return f"{qualify(details.birth, details.birth_uncertain)}–{qualify(details.death, details.death_uncertain)}"
    if details.death and not details.birth:
        return f"–{qualify(details.death, details.death_uncertain)}"
    if details.birth and not details.death:
        return f"{qualify(details.birth, details.birth_uncertain)}–"
    if (
        details.floruit
        and details.floruit.from_value
        and details.floruit.to_value
    ):
        return (
            f"fl. {format_precision_date(details.floruit.from_value, details.floruit.from_precision)}"
            f"–{format_precision_date(details.floruit.to_value, details.floruit.to_precision)}"
        )
    return None


def display_label_for_person(details: EntityDetails) -> str:
    suffix = display_date_suffix(details)
    if suffix and suffix not in details.label:
        return f"{details.label}, {suffix}"
    return details.label


def strip_existing_person_date_suffix(label: str) -> str:
    stripped = " ".join(label.split())
    if ", " not in stripped:
        return stripped
    head, tail = stripped.rsplit(", ", 1)
    if re.fullmatch(r"(?:fl\. )?[0-9?][0-9?sS.\-–]*", tail):
        return head
    if re.fullmatch(r"[0-9?]*-[0-9?]*", tail):
        return head
    if re.fullmatch(r"[–-][0-9?]+", tail):
        return head
    return stripped


def claim_entity_qids(entity: dict[str, object] | None, pid: str) -> list[str]:
    if not entity:
        return []
    qids: list[str] = []
    for claim_value in get_claim_value_objects(entity, pid):
        qid = claim_value.entity_id()
        if qid and qid not in qids:
            qids.append(qid)
    return qids


def reorder_person_label_surname_first(
    label: str, given_name: str | None, family_name: str | None
) -> tuple[str, str | None]:
    if "," in label:
        return label, None

    stripped = " ".join(label.split())
    if not stripped:
        return label, None

    if given_name and family_name:
        given = " ".join(given_name.split())
        family = " ".join(family_name.split())
        if not given or not family:
            return label, None

        if stripped == f"{given} {family}":
            return f"{family}, {given}", "surnameFirst"

        if stripped.startswith(f"{given} ") and stripped.endswith(f" {family}"):
            middle = stripped[len(given) : len(stripped) - len(family)].strip()
            if middle and any(
                token == token.lower() for token in middle.split()
            ):
                return label, None
            reordered = f"{family}, {given}"
            if middle:
                reordered = f"{family}, {given} {middle}"
            return reordered, "surnameFirst"

    return label, None


def strip_honorific_prefix(label: str, honorific_prefix: str | None) -> str:
    if not honorific_prefix:
        return label
    prefix = " ".join(honorific_prefix.split())
    if not prefix:
        return label
    if label.startswith(f"{prefix} "):
        return label[len(prefix) + 1 :]
    return label


def apply_honorific_prefix(
    label: str, honorific_prefix: str | None, surname_first: bool
) -> str:
    if not honorific_prefix:
        return label
    prefix = " ".join(honorific_prefix.split())
    if not prefix:
        return label
    if label.startswith(f"{prefix} ") or f", {prefix} " in label:
        return label
    if surname_first and ", " in label:
        family, rest = label.split(", ", 1)
        return f"{family}, {prefix} {rest}"
    return f"{prefix} {label}"


def rounded_coordinate_text(value: float, precision: float | None) -> str:
    decimals = 6
    if isinstance(precision, (int, float)) and precision > 0:
        decimals = max(0, int(math.ceil(-math.log10(float(precision)))))
    rendered = f"{round(value, decimals):.{decimals}f}"
    return rendered.rstrip("0").rstrip(".")


def claim_coordinates(
    entity: dict[str, object] | None,
) -> CoordinatePoint | None:
    if not entity:
        return None
    for value in get_claim_values(entity, "P625"):
        lat = value.get("latitude")
        lon = value.get("longitude")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            precision = value.get("precision")
            precision_value = (
                float(precision)
                if isinstance(precision, (int, float))
                else None
            )
            return CoordinatePoint(
                latitude=rounded_coordinate_text(float(lat), precision_value),
                longitude=rounded_coordinate_text(float(lon), precision_value),
            )
    return None


def place_type_from_entity(entity: dict[str, object] | None) -> str:
    type_qids = set(claim_entity_qids(entity, "P31"))
    if type_qids & COUNTRY_TYPE_QIDS:
        return "country"
    if type_qids & SETTLEMENT_TYPE_QIDS:
        return "settlement"
    if type_qids & REGION_TYPE_QIDS:
        return "region"
    return "region"


def build_link_items(
    entity: dict[str, object] | None,
    qid: str,
    mapping: list[tuple[str, str, str]],
) -> tuple[LinkItem, ...]:
    links: list[LinkItem] = [
        LinkItem(
            title="Wikidata", target=f"https://www.wikidata.org/entity/{qid}"
        )
    ]
    seen = {links[0].target}

    for pid, label, template in mapping:
        for value in claim_string_values(entity, pid):
            url = template.format(value=escape(value))
            if url not in seen:
                links.append(LinkItem(title=label, target=url))
                seen.add(url)

    return tuple(links)


def links_note_xml(links: tuple[LinkItem, ...], indent: str) -> list[str]:
    lines = [f'{indent}<note type="links">', f'{indent}   <list type="links">']
    for item in links:
        lines.extend(
            [
                f"{indent}      <item>",
                f'{indent}         <ref target="{escape(item.target, {'"': "&quot;"})}">',
                f"{indent}            <title>{escape(item.title)}</title>",
                f"{indent}         </ref>",
                f"{indent}      </item>",
            ]
        )
    lines.extend([f"{indent}   </list>", f"{indent}</note>"])
    return lines


def sort_key_for_link_title(title: str) -> str:
    normalized = " ".join(title.split()).casefold()
    normalized = re.sub(r"^(a|an|the)\s+", "", normalized)
    decomposed = unicodedata.normalize("NFKD", normalized)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def dedupe_links(
    links: tuple[LinkItem, ...] | list[LinkItem],
) -> tuple[LinkItem, ...]:
    deduped: list[LinkItem] = []
    seen: set[str] = set()
    for link in links:
        if link.target not in seen:
            deduped.append(link)
            seen.add(link.target)
    deduped.sort(
        key=lambda link: (
            sort_key_for_link_title(link.title),
            link.title.casefold(),
            link.target,
        )
    )
    return tuple(deduped)


def language_code_for_qid(lang_qid: str, client: WikidataClient) -> str | None:
    entity = client.get_entity(lang_qid)
    if not entity:
        return None
    for pid in ("P218", "P219", "P220", "P424"):
        values = claim_string_values(entity, pid)
        if values:
            code = values[0].strip().lower()
            if code:
                return code
    return None


def language_label_for_qid(lang_qid: str, client: WikidataClient) -> str | None:
    entity = client.get_entity(lang_qid)
    label = preferred_label(entity, lang_qid).value
    if label and label != lang_qid:
        return label
    return None


def collect_linked_authority_refs(
    entity: dict[str, object] | None,
    pid: str,
    related_type: EntityType,
    client: WikidataClient,
    ensure_related: EnsureRelatedFn | None,
    relation_type: str | None = None,
) -> tuple[LinkedAuthorityRef, ...]:
    if not entity or ensure_related is None:
        return ()
    refs: list[LinkedAuthorityRef] = []
    seen: set[str] = set()
    for related_qid in claim_entity_qids(entity, pid):
        fallback_label = preferred_label(
            client.get_entity(related_qid), related_qid
        ).value
        key, label = ensure_related(related_type, related_qid, fallback_label)
        if key not in seen:
            refs.append(
                LinkedAuthorityRef(
                    key=key, label=label, relation_type=relation_type
                )
            )
            seen.add(key)
    return tuple(refs)


def collect_occupation_variants(
    entity: dict[str, object] | None, client: WikidataClient
) -> tuple[NameVariant, ...]:
    if not entity:
        return ()
    occupations: list[NameVariant] = []
    seen: set[tuple[str, str | None]] = set()
    for occupation_qid in claim_entity_qids(entity, "P106"):
        occupation_label = preferred_label(
            client.get_entity(occupation_qid), occupation_qid
        )
        key = (occupation_label.value, occupation_label.lang)
        if occupation_label.value and key not in seen:
            occupations.append(occupation_label)
            seen.add(key)
    return tuple(occupations)


def build_person_details(
    qid: str,
    fallback: str,
    client: WikidataClient,
    ensure_related: EnsureRelatedFn | None = None,
) -> EntityDetails:
    entity = client.get_entity(qid)
    display = preferred_label(entity, fallback)
    display_value = strip_existing_person_date_suffix(display.value)
    given_qids = claim_entity_qids(entity, "P735")
    family_qids = claim_entity_qids(entity, "P734")
    honorific_qids = claim_entity_qids(entity, "P511")
    related_qids = [
        *given_qids,
        *family_qids,
        *honorific_qids,
        *claim_entity_qids(entity, "P611"),
        *claim_entity_qids(entity, "P937"),
        *claim_entity_qids(entity, "P69"),
        *claim_entity_qids(entity, "P27"),
        *claim_entity_qids(entity, "P551"),
        *claim_entity_qids(entity, "P106"),
    ]
    client.get_entities(related_qids)
    given_name = (
        preferred_label(client.get_entity(given_qids[0]), given_qids[0]).value
        if given_qids
        else None
    )
    family_name = (
        preferred_label(client.get_entity(family_qids[0]), family_qids[0]).value
        if family_qids
        else None
    )
    honorific_prefix = (
        preferred_label(
            client.get_entity(honorific_qids[0]), honorific_qids[0]
        ).value
        if honorific_qids
        else None
    )
    sortable_display_value = strip_honorific_prefix(
        display_value, honorific_prefix
    )
    normalized_label, display_subtype = reorder_person_label_surname_first(
        sortable_display_value, given_name, family_name
    )
    normalized_label = apply_honorific_prefix(
        normalized_label, honorific_prefix, display_subtype == "surnameFirst"
    )
    normalized_display = NameVariant(normalized_label, display.lang)
    curated_links = build_link_items(entity, qid, PERSON_ID_LINKS)
    generic_links = external_id_links(
        entity, client, excluded_pids={pid for pid, _, _ in PERSON_ID_LINKS}
    )
    birth, birth_uncertain = first_time_with_circumstances(
        entity, "P569", client, min_precision=9
    )
    death, death_uncertain = first_time_with_circumstances(
        entity, "P570", client, min_precision=9
    )
    affiliations = [
        *collect_linked_authority_refs(
            entity,
            "P611",
            EntityType.ORG,
            client,
            ensure_related,
            relation_type="religiousOrder",
        ),
        *collect_linked_authority_refs(
            entity,
            "P937",
            EntityType.ORG,
            client,
            ensure_related,
            relation_type="workPlace",
        ),
    ]
    return EntityDetails(
        qid=qid,
        label=normalized_label,
        label_lang=display.lang,
        display_subtype=display_subtype,
        honorific_prefix=honorific_prefix,
        variants=collect_variants(entity, normalized_display),
        birth=birth,
        birth_uncertain=birth_uncertain,
        death=death,
        death_uncertain=death_uncertain,
        floruit=floruit_from_entity(entity),
        sex=sex_from_entity(entity),
        affiliations=tuple(affiliations),
        educations=collect_linked_authority_refs(
            entity, "P69", EntityType.ORG, client, ensure_related
        ),
        nationalities=collect_linked_authority_refs(
            entity, "P27", EntityType.PLACE, client, ensure_related
        ),
        residences=collect_linked_authority_refs(
            entity, "P551", EntityType.PLACE, client, ensure_related
        ),
        occupations=collect_occupation_variants(entity, client),
        links=dedupe_links((*generic_links, *curated_links)),
        external_ids=ExternalAuthorityIds(
            viaf=first_numeric_identifier(entity, "P214")
        ),
    )


def build_place_details(
    qid: str, fallback: str, client: WikidataClient
) -> EntityDetails:
    entity = client.get_entity(qid)
    display = preferred_label(entity, fallback)
    coordinates = claim_coordinates(entity)
    curated_pids = {pid for pid, _, _ in PLACE_ID_LINKS}
    return EntityDetails(
        qid=qid,
        label=display.value,
        label_lang=display.lang,
        variants=collect_variants(entity, display),
        links=dedupe_links(
            (
                *external_id_links(entity, client, excluded_pids=curated_pids),
                *build_link_items(entity, qid, PLACE_ID_LINKS),
            )
        ),
        coordinates=coordinates,
        place_type=place_type_from_entity(entity),
        external_ids=ExternalAuthorityIds(
            geonames=first_numeric_identifier(entity, "P1566"),
            tgn=first_numeric_identifier(entity, "P1667"),
        ),
    )


def build_org_details(
    qid: str, fallback: str, client: WikidataClient
) -> EntityDetails:
    entity = client.get_entity(qid)
    display = preferred_label(entity, fallback)
    curated_pids = {pid for pid, _, _ in PERSON_ID_LINKS}
    return EntityDetails(
        qid=qid,
        label=display.value,
        label_lang=display.lang,
        variants=collect_variants(entity, display),
        links=dedupe_links(
            (
                *external_id_links(entity, client, excluded_pids=curated_pids),
                *build_link_items(entity, qid, PERSON_ID_LINKS),
            )
        ),
        external_ids=ExternalAuthorityIds(
            viaf=first_numeric_identifier(entity, "P214")
        ),
    )


def build_work_details(
    qid: str,
    fallback: str,
    client: WikidataClient,
    ensure_person: EnsurePersonFn,
    preferred_author_key: str | None = None,
    preferred_author_text: str | None = None,
) -> EntityDetails:
    entity = client.get_entity(qid)
    display = preferred_label(entity, fallback)

    authors: list[WorkAuthor] = []
    for author_qid in claim_entity_qids(entity, "P50"):
        author_key, author_label, author_source = ensure_person(
            author_qid, preferred_author_key, None
        )
        authors.append(
            WorkAuthor(key=author_key, label=author_label, source=author_source)
        )
    if not authors and preferred_author_key:
        fallback_author_key, fallback_author_label, fallback_author_source = (
            ensure_person(None, preferred_author_key, preferred_author_text)
        )
        authors.append(
            WorkAuthor(
                key=fallback_author_key,
                label=fallback_author_label,
                source=fallback_author_source,
            )
        )

    main_lang = "und"
    main_lang_label: str | None = None
    for lang_qid in claim_entity_qids(entity, "P407"):
        code = language_code_for_qid(lang_qid, client)
        if code:
            main_lang = code
            main_lang_label = language_label_for_qid(lang_qid, client)
            break

    incipit = first_monolingual_text(entity, "P1922")

    return EntityDetails(
        qid=qid,
        label=display.value,
        label_lang=display.lang,
        variants=collect_variants(entity, display),
        links=dedupe_links(
            (
                *external_id_links(
                    entity,
                    client,
                    excluded_pids={pid for pid, _, _ in WORK_ID_LINKS},
                ),
                *build_link_items(entity, qid, WORK_ID_LINKS),
            )
        ),
        main_lang=main_lang,
        main_lang_label=main_lang_label,
        incipit=incipit[0] if incipit else None,
        incipit_lang=incipit[1] if incipit else None,
        authors=tuple(authors),
        external_ids=ExternalAuthorityIds(
            viaf=first_numeric_identifier(entity, "P214")
        ),
    )


def build_person_snippet(key: str, details: EntityDetails) -> str:
    lines = [f'            <person xml:id="{key}">']
    lines.append(
        f"               <persName{format_attrs(source='Wikidata', subtype=details.display_subtype, type='display')}>{escape(display_label_for_person(details))}</persName>"
    )
    for variant in details.variants:
        lines.append(
            f"               <persName{format_attrs(source='Wikidata', type='variant', **{'xml:lang': variant.lang})}>{escape(variant.value)}</persName>"
        )
    if details.birth:
        lines.append(
            f"               <birth{format_attrs(cert='medium' if details.birth_uncertain else None, source='Wikidata', when=details.birth)}/>"
        )
    if details.death:
        lines.append(
            f"               <death{format_attrs(cert='medium' if details.death_uncertain else None, source='Wikidata', when=details.death)}/>"
        )
    if details.floruit and (
        details.floruit.from_value or details.floruit.to_value
    ):
        floruit_attrs: dict[str, str | None] = {
            "cert": floruit_certainty(details.floruit),
            "from": details.floruit.from_value,
            "to": details.floruit.to_value,
        }
        parts = [
            f'{name}="{escape(value)}"'
            for name, value in sorted(floruit_attrs.items())
            if value is not None
        ]
        lines.append(f"               <floruit {' '.join(parts)}/>")
    if details.sex:
        lines.append(
            f"               <sex{format_attrs(source='Wikidata')}>{details.sex}</sex>"
        )
    for affiliation in details.affiliations:
        lines.append(
            f"               <affiliation{format_attrs(type=affiliation.relation_type)}><orgName{format_attrs(key=affiliation.key, source='Wikidata')}>{escape(affiliation.label)}</orgName></affiliation>"
        )
    for education in details.educations:
        lines.append(
            f"               <education><orgName{format_attrs(key=education.key, source='Wikidata')}>{escape(education.label)}</orgName></education>"
        )
    for nationality in details.nationalities:
        lines.append(
            f"               <nationality{format_attrs(key=nationality.key, source='Wikidata')}>{escape(nationality.label)}</nationality>"
        )
    for residence in details.residences:
        lines.append(
            f"               <residence><placeName{format_attrs(key=residence.key, source='Wikidata')}>{escape(residence.label)}</placeName></residence>"
        )
    for occupation in details.occupations:
        lines.append(
            f"               <occupation{format_attrs(source='Wikidata', **{'xml:lang': occupation.lang})}>{escape(occupation.value)}</occupation>"
        )
    lines.extend(links_note_xml(details.links, "               "))
    lines.append("            </person>")
    return "\n".join(lines)


def build_place_snippet(key: str, details: EntityDetails) -> str:
    lines = [
        f"            <place{format_attrs(type=details.place_type, **{'xml:id': key})}>"
    ]
    lines.append(
        f"               <placeName{format_attrs(source='Wikidata', type='index')}>{escape(details.label)}</placeName>"
    )
    for variant in details.variants:
        lines.append(
            f"               <placeName{format_attrs(source='Wikidata', type='variant', **{'xml:lang': variant.lang})}>{escape(variant.value)}</placeName>"
        )
    if details.coordinates is not None:
        lines.append(
            f'               <location source="https://www.wikidata.org/entity/{details.qid}">'
        )
        lines.append(
            f"                  <geo>{details.coordinates.latitude},{details.coordinates.longitude}</geo>"
        )
        lines.append("               </location>")
    lines.extend(links_note_xml(details.links, "               "))
    lines.append("            </place>")
    return "\n".join(lines)


def build_org_snippet(key: str, details: EntityDetails) -> str:
    lines = [f'            <org xml:id="{key}">']
    lines.append(
        f"               <orgName{format_attrs(source='Wikidata', type='display')}>{escape(details.label)}</orgName>"
    )
    for variant in details.variants:
        lines.append(
            f"               <orgName{format_attrs(source='Wikidata', type='variant', **{'xml:lang': variant.lang})}>{escape(variant.value)}</orgName>"
        )
    lines.extend(links_note_xml(details.links, "               "))
    lines.append("            </org>")
    return "\n".join(lines)


def build_work_snippet(key: str, details: EntityDetails) -> str:
    lines = [f'            <bibl xml:id="{key}">']
    for author in details.authors:
        lines.append(
            f"               <author{format_attrs(key=author.key, source=author.source)}>{escape(author.label)}</author>"
        )
    uniform_parts: list[str] = []
    if details.authors:
        uniform_parts.append(
            "; ".join(author.label for author in details.authors)
        )
        uniform_parts.append(": ")
    uniform_parts.append(details.label)
    if details.main_lang_label:
        uniform_parts.append(f" [{details.main_lang_label}]")
    lines.append(
        f"               <title{format_attrs(source='Wikidata', type='uniform')}>{escape(''.join(uniform_parts))}</title>"
    )
    for variant in details.variants:
        lines.append(
            f"               <title{format_attrs(source='Wikidata', type='variant', **{'xml:lang': variant.lang})}>{escape(variant.value)}</title>"
        )
    lines.append(
        f'               <textLang mainLang="{escape(details.main_lang or "und")}"/>'
    )
    if details.incipit:
        lines.append(
            f"               <incipit{format_attrs(source='Wikidata', **{'xml:lang': details.incipit_lang})}>{escape(details.incipit)}</incipit>"
        )
    lines.extend(links_note_xml(details.links, "               "))
    lines.append("            </bibl>")
    return "\n".join(lines)


def route_entity(
    details: EntityDetails, entity_type: EntityType
) -> AuthorityListSpec:
    if entity_type == "place":
        if details.external_ids.geonames:
            return AuthorityListSpec("listPlace", "geonames", "place", "place")
        if details.external_ids.tgn:
            return AuthorityListSpec("listPlace", "TGN", "place", "place")
        return AuthorityListSpec("listPlace", "local", "place", "place")

    if entity_type == "person":
        if details.external_ids.viaf:
            return AuthorityListSpec("listPerson", "VIAF", "person", "person")
        return AuthorityListSpec("listPerson", "local", "person", "person")

    if entity_type == "org":
        if details.external_ids.viaf:
            return AuthorityListSpec("listOrg", "VIAF", "org", "org")
        return AuthorityListSpec("listOrg", "local", "org", "org")

    if details.authors:
        return AuthorityListSpec("listBibl", "authors", "bibl", "work")
    return AuthorityListSpec("listBibl", "anonymous", "bibl", "work")


def assign_key_for_details(
    details: EntityDetails,
    entity_type: EntityType,
    used_ids: dict[str, set[int]],
    min_ids: dict[str, int],
) -> str:
    prefix = entity_to_prefix(entity_type)

    explicit_id: str | None = None
    if entity_type in {EntityType.PERSON, EntityType.ORG}:
        explicit_id = details.external_ids.viaf
    elif entity_type == EntityType.PLACE:
        explicit_id = details.external_ids.geonames or details.external_ids.tgn

    if explicit_id is not None:
        numeric_id = int(explicit_id)
        if numeric_id in used_ids[prefix]:
            raise ValueError(
                f"Cannot create {prefix}_{numeric_id}: numeric ID already exists in authority file"
            )
        used_ids[prefix].add(numeric_id)
        return f"{prefix}_{numeric_id}"

    return f"{prefix}_{next_available_id(used_ids[prefix], min_ids[prefix])}"


def key_number(key: str) -> int:
    match = ID_RE.match(key)
    if not match:
        raise ValueError(f"Invalid authority key: {key}")
    return int(match.group(2))


def attribute_sort_name(attr_name: str) -> str:
    if attr_name.startswith("{"):
        namespace, local_name = attr_name[1:].split("}", 1)
        if namespace == NS["xml"]:
            return f"xml:{local_name}"
        return local_name
    return attr_name


def sort_attributes(node: etree._Element) -> None:
    sorted_items = sorted(
        node.attrib.items(), key=lambda item: attribute_sort_name(str(item[0]))
    )
    node.attrib.clear()
    for name, value in sorted_items:
        node.set(name, value)


def format_attrs(**attrs: str | None) -> str:
    parts: list[str] = []
    for name in sorted(attrs.keys()):
        value = attrs[name]
        if value is None:
            continue
        parts.append(f'{name}="{escape(value)}"')
    return f" {' '.join(parts)}" if parts else ""


def normalize_document_header(xml_text: str) -> str:
    xml_text = re.sub(r"\?>\s*(<\?xml-model\b)", r"?>\n\1", xml_text)
    xml_text = re.sub(r"\?>\s*(<TEI\b)", r"?>\n\1", xml_text)
    return xml_text


def preserve_root_tei_start_tag(xml_text: str, original_text: str) -> str:
    original_match = re.search(r"<TEI\b[^>]*>", original_text)
    new_match = re.search(r"<TEI\b[^>]*>", xml_text)
    if not original_match or not new_match:
        return xml_text
    return (
        xml_text[: new_match.start()]
        + original_match.group(0)
        + xml_text[new_match.end() :]
    )


def write_preserving_header(
    tree: etree._ElementTree, file_path: Path, original_text: str
) -> None:
    xml_text = etree.tostring(
        tree, encoding="unicode", xml_declaration=False, pretty_print=False
    )
    xml_text = normalize_document_header(xml_text)
    xml_text = preserve_root_tei_start_tag(xml_text, original_text)
    file_path.write_text(xml_text, encoding="utf-8")


def leading_indent_before(text: str, pos: int) -> str:
    line_start = text.rfind("\n", 0, pos)
    if line_start == -1:
        return ""
    indent = text[line_start + 1 : pos]
    return indent if indent.isspace() else ""


def split_trailing_comment_block(text: str) -> tuple[str, str]:
    match = re.search(r"(\s*(?:<!--.*?-->\s*)+)$", text, re.DOTALL)
    if match is None:
        return text, ""
    return text[: match.start(1)], match.group(1)


def reindent_snippet(snippet: str, indent: str) -> str:
    body = textwrap.dedent(snippet).strip("\n")
    return "\n".join(
        f"{indent}{line}" if line else line for line in body.splitlines()
    )


def split_trailing_line_indent(text: str) -> tuple[str, str]:
    line_start = text.rfind("\n")
    if line_start == -1:
        return text, ""
    trailing = text[line_start + 1 :]
    if trailing and trailing.isspace():
        return text[: line_start + 1], trailing
    return text, ""


def is_within_xml_comment(text: str, pos: int) -> bool:
    last_open = text.rfind("<!--", 0, pos)
    if last_open == -1:
        return False
    last_close = text.rfind("-->", 0, pos)
    return last_open > last_close


def best_insertion_gap(existing_numbers: list[int], new_number: int) -> int:
    total_lower = sum(1 for number in existing_numbers if number < new_number)
    lower_before = 0
    greater_before = 0
    best_gap = 0
    best_score: int | None = None

    for gap in range(len(existing_numbers) + 1):
        lower_after = total_lower - lower_before
        score = greater_before + lower_after
        if (
            best_score is None
            or score < best_score
            or (score == best_score and gap > best_gap)
        ):
            best_gap = gap
            best_score = score
        if gap == len(existing_numbers):
            break
        current = existing_numbers[gap]
        if current < new_number:
            lower_before += 1
        elif current > new_number:
            greater_before += 1

    return best_gap


def insert_entries_in_numeric_order(
    path: Path,
    list_tag: str,
    list_type: str | None,
    child_tag: str,
    prefix: str,
    entries: list[PlannedEntry],
) -> None:
    """Insert prepared snippets into a TEI list in numeric ``xml:id`` order."""

    if not entries:
        return

    source = path.read_text(encoding="utf-8")
    if list_type is None:
        pattern = re.compile(
            rf"(<{list_tag}\b[^>]*>)(.*?)(</{list_tag}>)", re.DOTALL
        )
    else:
        pattern = re.compile(
            rf"(<{list_tag}\b[^>]*\btype=\"{re.escape(list_type)}\"[^>]*>)(.*?)(</{list_tag}>)",
            re.DOTALL,
        )

    match = pattern.search(source)
    if match is None:
        if list_type is None:
            raise ValueError(f"Could not find <{list_tag}> in {path}")
        raise ValueError(
            f'Could not find <{list_tag} type="{list_type}"> in {path}'
        )

    content = match.group(2)
    child_pattern = re.compile(
        rf"<{child_tag}\b[^>]*\bxml:id=\"{re.escape(prefix)}_(\d+)\"[^>]*>",
        re.DOTALL,
    )
    existing_matches = [
        match
        for match in child_pattern.finditer(content)
        if not is_within_xml_comment(content, match.start())
    ]
    pending = sorted(entries, key=lambda entry: key_number(entry.key))
    existing_numbers = [
        int(existing_match.group(1)) for existing_match in existing_matches
    ]
    entries_by_gap: dict[int, list[PlannedEntry]] = {}
    for entry in pending:
        gap = best_insertion_gap(existing_numbers, key_number(entry.key))
        entries_by_gap.setdefault(gap, []).append(entry)
    child_indent = (
        leading_indent_before(content, existing_matches[0].start())
        if existing_matches
        else "            "
    )

    rebuilt_parts: list[str] = []
    cursor = 0

    for existing_index, existing_match in enumerate(existing_matches):
        segment = content[cursor : existing_match.start()]
        prefix_text, trailing_comments = split_trailing_comment_block(segment)
        gap_entries = entries_by_gap.get(existing_index, [])
        will_insert_before_existing = bool(gap_entries)
        if will_insert_before_existing:
            prefix_text, stripped_indent = split_trailing_line_indent(
                prefix_text
            )
            if stripped_indent and not child_indent:
                child_indent = stripped_indent
        if (
            cursor == 0
            and will_insert_before_existing
            and prefix_text.strip() == ""
        ):
            prefix_text = "\n" if "\n" in prefix_text else ""
        rebuilt_parts.append(prefix_text)
        cursor = existing_match.start()
        existing_indent = leading_indent_before(content, existing_match.start())
        inserted_before_existing = bool(gap_entries)
        for entry in gap_entries:
            formatted_snippet = reindent_snippet(
                entry.xml_snippet, existing_indent or child_indent
            )
            if (
                rebuilt_parts
                and rebuilt_parts[-1]
                and rebuilt_parts[-1].strip()
                and not rebuilt_parts[-1].endswith("\n")
            ):
                rebuilt_parts.append("\n")
            rebuilt_parts.append(formatted_snippet + "\n")
            if (
                existing_indent
                and not trailing_comments
                and entry is gap_entries[-1]
            ):
                rebuilt_parts.append(existing_indent)
        if inserted_before_existing and trailing_comments:
            stripped_comments = trailing_comments.lstrip()
            if stripped_comments.startswith("<!--"):
                trailing_comments = f"\n{existing_indent}{stripped_comments}"
        rebuilt_parts.append(trailing_comments)

    trailing_entries = entries_by_gap.get(len(existing_matches), [])
    tail_content = content[cursor:]
    tail_indent = ""
    if trailing_entries:
        tail_content, tail_indent = split_trailing_line_indent(tail_content)
    rebuilt_parts.append(tail_content)

    if trailing_entries:
        trailing = "\n".join(
            reindent_snippet(entry.xml_snippet, child_indent)
            for entry in trailing_entries
        )
        if (
            rebuilt_parts
            and rebuilt_parts[-1]
            and not rebuilt_parts[-1].endswith("\n")
        ):
            rebuilt_parts.append("\n")
        rebuilt_parts.append(trailing + "\n")
        if tail_indent:
            rebuilt_parts.append(tail_indent)

    new_content = "".join(rebuilt_parts)
    updated = source[: match.start(2)] + new_content + source[match.end(2) :]
    path.write_text(updated, encoding="utf-8")


def apply_key_updates(
    candidates: list[Candidate],
    key_map: dict[tuple[EntityType, str], str],
    keep_ref: bool,
) -> int:
    changed_files = 0
    by_file: dict[Path, list[Candidate]] = {}
    for candidate in candidates:
        by_file.setdefault(candidate.file_path, []).append(candidate)

    for file_path in by_file:
        original_text = file_path.read_text(encoding="utf-8")
        tree = parse_xml(file_path)
        dirty = False
        for node in xpath_elements(tree, XPATH_CANDIDATES):
            local = etree.QName(node.tag).localname
            entity_type = element_to_entity(local)
            if entity_type is None:
                continue

            qid = extract_qid(node.get("ref", ""))
            if not qid:
                continue

            key = key_map.get((entity_type, qid))
            if not key:
                continue

            node.set("key", key)
            if not keep_ref and "ref" in node.attrib:
                del node.attrib["ref"]
            sort_attributes(node)
            dirty = True

        if dirty:
            write_preserving_header(tree, file_path, original_text)
            changed_files += 1

    return changed_files


def run_regenerate(args: argparse.Namespace, client: WikidataClient) -> int:
    """Execute the ``authorities regenerate`` workflow."""

    repository = AuthorityRepository(
        AuthorityPaths(
            persons=args.persons, places=args.places, works=args.works
        )
    )
    regenerated: list[tuple[str, str]] = []
    created_related_messages: list[tuple[str, str]] = []
    regeneration_state = RegenerationState.load(repository=repository)
    for spec in args.entries:
        key, qid = parse_regenerate_spec(spec)
        if qid is None:
            authority_path, _, child_tag = repository.paths.for_key(key)
            qid = existing_entry_wikidata_qid(authority_path, key, child_tag)
            if qid is None:
                raise ValueError(
                    f"Cannot regenerate {key} without an explicit Wikidata QID: no existing Wikidata link was found"
                )
        authority_path, entity_type, created_related = regenerate_entry(
            key,
            qid,
            persons_path=repository.paths.persons,
            places_path=repository.paths.places,
            works_path=repository.paths.works,
            client=client,
            min_ids={
                "person": args.person_min_id,
                "place": args.place_min_id,
                "org": args.org_min_id,
                "work": args.work_min_id,
            },
            regeneration_state=regeneration_state,
        )
        regenerated.append(
            (str(authority_path), f"{key} <- {qid} ({entity_type})")
        )
        for entry in created_related:
            target_path = (
                args.places
                if entry.entity_type in {EntityType.PLACE, EntityType.ORG}
                else authority_path
            )
            created_related_messages.append(
                (
                    str(target_path),
                    f"created related {entry.key} <- {entry.qid} ({entry.entity_type}: {entry.label}) for {key}",
                )
            )
    for path, message in regenerated:
        print(f"{path}: regenerated {message}")
    for path, message in created_related_messages:
        print(f"{path}: {message}")
    return 0


def run_reconcile(args: argparse.Namespace, client: WikidataClient) -> int:
    """Execute the ``authorities reconcile`` workflow."""

    if not args.persons.exists():
        raise FileNotFoundError(f"Missing file: {args.persons}")
    if args.apply:
        if not args.report.exists():
            raise FileNotFoundError(f"Missing file: {args.report}")
        approved = approved_reconciliations_from_report(args.report)
        changed = apply_approved_person_reconciliations(args.persons, approved)
        print(f"Approved reconciliations found: {len(approved)}")
        print(f"Updated person entries: {changed}")
        return 0
    reconciliations = reconcile_existing_persons(
        args.persons, client, args.reconcile_limit
    )
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "reconcile-existing",
        "authority_file": str(args.persons),
        "reconciled_count": len(reconciliations),
        "entries": reconciliations,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8"
    )
    print(f"Existing person entries reviewed: {len(reconciliations)}")
    print(f"Report written: {args.report}")
    return 0


def run_enrich(args: argparse.Namespace, client: WikidataClient) -> int:
    """Execute the ``authorities enrich`` workflow."""
    repository = AuthorityRepository(
        AuthorityPaths(
            persons=args.persons, places=args.places, works=args.works
        )
    )

    apply_changes = not getattr(args, "dry_run", False)

    if args.inputs:
        xml_paths = [Path(p) for p in args.inputs]
    else:
        xml_paths = sorted(Path("collections").rglob("*.xml"))

    for path in [*xml_paths, args.persons, args.places, args.works]:
        if not path.exists():
            raise FileNotFoundError(f"Missing file: {path}")

    ensure_unique_authority_identifiers([args.persons, args.places, args.works])

    candidates = collect_candidates(xml_paths)

    existing_maps: dict[EntityType, dict[str, str]] = {
        EntityType.PERSON: repository.qid_map(EntityType.PERSON),
        EntityType.PLACE: repository.qid_map(EntityType.PLACE),
        EntityType.ORG: repository.qid_map(EntityType.ORG),
        EntityType.WORK: repository.qid_map(EntityType.WORK),
    }
    person_display_map = repository.display_map(EntityType.PERSON)
    place_display_map = repository.display_map(EntityType.PLACE)
    org_display_map = repository.display_map(EntityType.ORG)
    person_authority_records = read_person_authority_records(args.persons)

    used_ids: dict[str, set[int]] = repository.used_ids()

    min_ids = {
        "person": args.person_min_id,
        "place": args.place_min_id,
        "org": args.org_min_id,
        "work": args.work_min_id,
    }

    key_map: dict[tuple[EntityType, str], str] = {}
    planned: dict[tuple[EntityType, str], PlannedEntry] = {}
    planned_person_display_map: dict[str, str] = {}
    planned_place_display_map: dict[str, str] = {}
    planned_org_display_map: dict[str, str] = {}

    fallback_by_target: dict[tuple[EntityType, str], str] = {}
    preferred_author_context_by_work_qid: dict[str, tuple[str, str | None]] = {}
    author_match_warnings: list[dict[str, str]] = []
    for candidate in candidates:
        fallback_by_target.setdefault(
            (candidate.entity_type, candidate.qid),
            candidate.text or candidate.qid,
        )
        if candidate.entity_type == "work" and candidate.context_author_key:
            preferred_author_context_by_work_qid.setdefault(
                candidate.qid,
                (candidate.context_author_key, candidate.context_author_text),
            )

    active_work_context: dict[str, str] = {}

    def ensure_related_for_person(
        entity_type: EntityType, qid: str, fallback_text: str
    ) -> tuple[str, str]:
        if entity_type not in {EntityType.PLACE, EntityType.ORG}:
            raise ValueError(
                f"Unsupported related entity type for person enrichment: {entity_type}"
            )
        equivalent_key = equivalent_local_key(entity_type, qid)
        if equivalent_key is not None:
            if entity_type == EntityType.PLACE:
                label = (
                    place_display_map.get(equivalent_key)
                    or fallback_text
                    or equivalent_key
                )
            else:
                label = (
                    org_display_map.get(equivalent_key)
                    or fallback_text
                    or equivalent_key
                )
            return equivalent_key, label
        key = ensure_entry(entity_type, qid, fallback_text)
        if entity_type == EntityType.PLACE:
            label = (
                place_display_map.get(key)
                or planned_place_display_map.get(key)
                or fallback_text
                or key
            )
        else:
            label = (
                org_display_map.get(key)
                or planned_org_display_map.get(key)
                or fallback_text
                or key
            )
        return key, label

    def ensure_person_for_work(
        author_qid: str | None,
        preferred_key: str | None = None,
        preferred_text: str | None = None,
    ) -> tuple[str, str, str | None]:
        if author_qid is None:
            if not preferred_key:
                raise ValueError(
                    "preferred_key is required when no author_qid is supplied"
                )
            label = (
                person_display_map.get(preferred_key)
                or person_authority_records.get(
                    preferred_key, PersonAuthorityRecord(preferred_key)
                ).display_label
                or preferred_text
                or preferred_key
            )
            return preferred_key, label, None

        author_entity = client.get_entity(author_qid)
        author_viaf = first_numeric_identifier(author_entity, "P214")

        if preferred_key:
            preferred_record = person_authority_records.get(preferred_key)
            if preferred_record:
                if author_qid in preferred_record.wikidata_qids or (
                    author_viaf is not None
                    and author_viaf in preferred_record.viaf_ids
                ):
                    key_map[(EntityType.PERSON, author_qid)] = preferred_key
                    label = (
                        preferred_record.display_label
                        or person_display_map.get(preferred_key)
                        or preferred_label(author_entity, author_qid).value
                    )
                    return preferred_key, label, None
                author_match_warnings.append(
                    {
                        "work_qid": active_work_context.get("qid", ""),
                        "work_title": active_work_context.get("title", ""),
                        "manuscript_author_key": preferred_key,
                        "wikidata_author_qid": author_qid,
                        "wikidata_author_viaf": author_viaf or "",
                        "reason": "manuscript author key did not match Wikidata author by QID or VIAF",
                    }
                )

        existing_key = existing_maps[EntityType.PERSON].get(author_qid)
        if not existing_key and author_viaf is not None:
            viaf_match_keys = [
                record.key
                for record in person_authority_records.values()
                if author_viaf in record.viaf_ids
            ]
            if len(viaf_match_keys) == 1:
                existing_key = viaf_match_keys[0]
                key_map[(EntityType.PERSON, author_qid)] = existing_key

        if existing_key:
            label = (
                person_display_map.get(existing_key)
                or person_authority_records.get(
                    existing_key, PersonAuthorityRecord(existing_key)
                ).display_label
                or preferred_label(author_entity, author_qid).value
            )
            return existing_key, label, None

        key = ensure_entry(EntityType.PERSON, author_qid, author_qid)
        if key in person_display_map:
            return key, person_display_map[key], None
        if key in planned_person_display_map:
            return key, planned_person_display_map[key], "Wikidata"
        return (
            key,
            display_label_for_person(
                build_person_details(author_qid, author_qid, client)
            ),
            "Wikidata",
        )

    def ensure_entry(
        entity_type: EntityType, qid: str, fallback_text: str
    ) -> str:
        target = (entity_type, qid)
        if target in key_map:
            return key_map[target]

        existing_key = existing_maps[entity_type].get(qid)
        if existing_key:
            key_map[target] = existing_key
            return existing_key

        if entity_type == EntityType.PERSON:
            details = build_person_details(
                qid, fallback_text or qid, client, ensure_related_for_person
            )
        elif entity_type == EntityType.PLACE:
            details = build_place_details(qid, fallback_text or qid, client)
        elif entity_type == EntityType.ORG:
            details = build_org_details(qid, fallback_text or qid, client)
        else:
            active_work_context["qid"] = qid
            active_work_context["title"] = fallback_text or qid
            details = build_work_details(
                qid,
                fallback_text or qid,
                client,
                ensure_person_for_work,
                preferred_author_key=preferred_author_context_by_work_qid.get(
                    qid, (None, None)
                )[0],
                preferred_author_text=preferred_author_context_by_work_qid.get(
                    qid, (None, None)
                )[1],
            )
            active_work_context.clear()

        list_spec = route_entity(details, entity_type)
        new_key = assign_key_for_details(
            details, entity_type, used_ids, min_ids
        )

        if entity_type == EntityType.PERSON:
            snippet = build_person_snippet(new_key, details)
            planned_person_display_map[new_key] = display_label_for_person(
                details
            )
        elif entity_type == EntityType.PLACE:
            snippet = build_place_snippet(new_key, details)
            planned_place_display_map[new_key] = details.label
        elif entity_type == EntityType.ORG:
            snippet = build_org_snippet(new_key, details)
            planned_org_display_map[new_key] = details.label
        else:
            snippet = build_work_snippet(new_key, details)

        key_map[target] = new_key
        planned[target] = PlannedEntry(
            qid=qid,
            key=new_key,
            entity_type=entity_type,
            label=display_label_for_person(details)
            if entity_type == EntityType.PERSON
            else details.label,
            list_spec=list_spec,
            external_ids=details.external_ids,
            xml_snippet=snippet,
        )
        return new_key

    # Ensure direct targets from manuscript refs
    for (entity_type, qid), fallback in sorted(
        fallback_by_target.items(), key=lambda x: (x[0][0], x[0][1])
    ):
        ensure_entry(entity_type, qid, fallback)

    # Collect new snippets per authority file
    entries_by_list: dict[tuple[str, str, str, str], list[PlannedEntry]] = {}
    for (_, _), entry in sorted(planned.items()):
        spec = entry.list_spec
        entries_by_list.setdefault(
            (spec.list_tag, spec.list_type, spec.child_tag, spec.prefix), []
        ).append(entry)

    changed_files = 0
    if apply_changes:
        for (
            list_tag,
            list_type,
            child_tag,
            prefix,
        ), entries in entries_by_list.items():
            repository.insert_entries(
                list_tag, list_type, child_tag, prefix, entries
            )
        changed_files = apply_key_updates(
            candidates, key_map, keep_ref=args.keep_ref
        )

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "apply": apply_changes,
        "input_files": [str(p) for p in xml_paths],
        "candidate_count": len(candidates),
        "unique_targets": len(fallback_by_target),
        "warnings": author_match_warnings,
        "new_entries": [
            {
                "entity_type": entry.entity_type,
                "qid": entry.qid,
                "key": entry.key,
                "label": entry.label,
                "list_type": entry.list_spec.list_type,
                "external_ids": {
                    "viaf": entry.external_ids.viaf,
                    "geonames": entry.external_ids.geonames,
                    "tgn": entry.external_ids.tgn,
                },
            }
            for _, entry in sorted(
                planned.items(), key=lambda x: (x[1].entity_type, x[1].key)
            )
        ],
        "manuscript_updates": [
            {
                "file": str(c.file_path),
                "element": c.element_name,
                "entity_type": c.entity_type,
                "qid": c.qid,
                "assigned_key": key_map.get((c.entity_type, c.qid)),
            }
            for c in candidates
        ],
        "changed_manuscript_files": changed_files,
    }

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8"
    )

    print(f"Candidates found: {len(candidates)}")
    print(f"Unique Wikidata targets: {len(fallback_by_target)}")
    print(f"New authority entries planned: {len(planned)}")
    print(f"Report written: {args.report}")

    if apply_changes:
        print(f"Applied manuscript updates in {changed_files} file(s)")
    else:
        print("Dry-run mode. No manuscript or authority files were modified.")

    return 0
