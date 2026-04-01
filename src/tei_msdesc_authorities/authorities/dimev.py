"""Minimal DIMEV client used for direct work creation."""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from time import time

from lxml import etree

DIMEV_RECORDS_XML_URL = (
    "https://raw.githubusercontent.com/"
    "digital-index-of-middle-english-verse/dimev/main/data/Records.xml"
)
DIMEV_RECORD_PATHS = {"/record.php", "/dimev/record.php"}
DEFAULT_CACHE_MAX_AGE_SECONDS = 24 * 60 * 60


@dataclass(slots=True, frozen=True)
class DimevAuthor:
    """Author metadata extracted from the DIMEV repository XML."""

    first: str | None = None
    last: str | None = None
    suffix: str | None = None

    @property
    def display_name(self) -> str:
        if self.last and self.first:
            rest = self.first
            if self.suffix:
                rest = f"{rest} {self.suffix}"
            return f"{self.last}, {rest}"
        parts = [part for part in (self.first, self.last, self.suffix) if part]
        return " ".join(parts)

    @property
    def natural_name(self) -> str:
        parts = [part for part in (self.first, self.last, self.suffix) if part]
        return " ".join(parts)

    @property
    def name_variants(self) -> tuple[str, ...]:
        variants: list[str] = []
        for candidate in (self.display_name, self.natural_name):
            if candidate and candidate not in variants:
                variants.append(candidate)
        return tuple(variants)


@dataclass(slots=True, frozen=True)
class DimevRecord:
    """Metadata extracted from the DIMEV repository XML."""

    record_id: str
    title: str
    title_variants: tuple[str, ...] = ()
    authors: tuple[DimevAuthor, ...] = ()
    first_lines: tuple[str, ...] = ()
    last_lines: tuple[str, ...] = ()
    subjects: tuple[str, ...] = ()
    imev_id: str | None = None
    nimev_id: str | None = None

    @property
    def record_url(self) -> str:
        return f"https://www.dimev.net/record.php?recID={self.record_id}"


def extract_dimev_id(ref: str) -> str | None:
    """Extract a DIMEV record ID from a supported ref value."""

    value = ref.strip()
    if not value:
        return None
    parsed = urllib.parse.urlparse(value)
    host = parsed.netloc.lower()
    if host not in {"dimev.net", "www.dimev.net", "dwm27.net", "www.dwm27.net"}:
        return None
    if parsed.path not in DIMEV_RECORD_PATHS:
        return None
    query = urllib.parse.parse_qs(parsed.query)
    for key, values in query.items():
        if key.lower() != "recid":
            continue
        for candidate in values:
            normalized = candidate.strip()
            if normalized.isdigit():
                return normalized
    return None


class DimevClient:
    """Fetch and parse DIMEV work records from repository XML."""

    def __init__(
        self,
        *,
        no_fetch: bool,
        cache_dir: Path | None = None,
        cache_max_age_seconds: int = DEFAULT_CACHE_MAX_AGE_SECONDS,
    ) -> None:
        self.no_fetch = no_fetch
        self.cache_dir = cache_dir or default_cache_dir()
        self.cache_max_age_seconds = max(0, cache_max_age_seconds)
        self.cache_path = self.cache_dir / "dimev-records.xml"
        self._record_cache: dict[str, DimevRecord | None] = {}
        self._records_tree: etree._Element | None = None
        self._last_error: str | None = None

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def get_record(self, record_id: str) -> DimevRecord | None:
        """Fetch one DIMEV record from the repository XML dataset."""

        normalized = record_id.strip()
        if not normalized.isdigit():
            self._last_error = f"Invalid DIMEV record ID: {record_id}"
            return None
        if normalized in self._record_cache:
            return self._record_cache[normalized]

        records_tree = self._load_records_tree()
        if records_tree is None:
            self._record_cache[normalized] = None
            return None

        record = parse_dimev_record(records_tree, normalized)
        if record is None:
            self._last_error = f"Could not find DIMEV record {normalized}"
        else:
            self._last_error = None
        self._record_cache[normalized] = record
        return record

    def _load_records_tree(self) -> etree._Element | None:
        if self._records_tree is not None:
            return self._records_tree

        fresh_cached = self._load_cached_records_tree(require_fresh=True)
        if fresh_cached is not None:
            self._records_tree = fresh_cached
            self._last_error = None
            return fresh_cached

        if self.no_fetch:
            stale_cached = self._load_cached_records_tree(require_fresh=False)
            if stale_cached is not None:
                self._records_tree = stale_cached
                self._last_error = None
                return stale_cached
            self._last_error = (
                "Fetching disabled by --no-fetch and no cached DIMEV XML is available"
            )
            return None

        request = urllib.request.Request(
            DIMEV_RECORDS_XML_URL,
            headers={
                "User-Agent": "tei-msdesc-authorities/1.0 (+https://github.com/medieval-mss)",
                "Accept": "application/xml,text/xml",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = response.read()
        except urllib.error.HTTPError as exc:
            self._last_error = f"HTTP {exc.code} from GitHub"
            return self._load_cached_records_tree(require_fresh=False)
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            self._last_error = (
                f"Network error talking to GitHub for DIMEV XML: {reason}"
            )
            return self._load_cached_records_tree(require_fresh=False)
        except TimeoutError:
            self._last_error = "Timed out fetching DIMEV XML from GitHub"
            return self._load_cached_records_tree(require_fresh=False)

        root = self._parse_records_xml(payload)
        if root is None:
            self._last_error = "Invalid XML returned for DIMEV records"
            return self._load_cached_records_tree(require_fresh=False)

        self._write_cache(payload)
        self._records_tree = root
        self._last_error = None
        return root

    def _load_cached_records_tree(
        self, *, require_fresh: bool
    ) -> etree._Element | None:
        if not self.cache_path.exists():
            return None
        if require_fresh and not self._cache_is_fresh():
            return None
        try:
            payload = self.cache_path.read_bytes()
        except OSError:
            return None
        return self._parse_records_xml(payload)

    def _cache_is_fresh(self) -> bool:
        try:
            modified = self.cache_path.stat().st_mtime
        except OSError:
            return False
        return (time() - modified) <= self.cache_max_age_seconds

    def _parse_records_xml(self, payload: bytes) -> etree._Element | None:
        try:
            return etree.fromstring(payload)
        except etree.XMLSyntaxError:
            return None

    def _write_cache(self, payload: bytes) -> None:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_bytes(payload)
        except OSError:
            return


def parse_dimev_record(
    records_root: etree._Element, record_id: str
) -> DimevRecord | None:
    """Parse the subset of one DIMEV XML record needed for work creation."""

    record: etree._Element | None = None
    target_id = f"record-{record_id}"
    for candidate in records_root.findall("./record"):
        if candidate.get("{http://www.w3.org/XML/1998/namespace}id") == target_id:
            record = candidate
            break
    if record is None:
        return None

    title = _child_text(record, "name")
    if not title:
        return None

    title_nodes = record.xpath("./titles/title")
    parsed_titles: list[str] = []
    for title_node in title_nodes:
        candidate = _itertext_space(title_node)
        if candidate and candidate not in parsed_titles:
            parsed_titles.append(candidate)
    preferred_title = parsed_titles[0] if parsed_titles else title
    title_variants = tuple(
        variant
        for variant in [*parsed_titles[1:], title]
        if variant and variant != preferred_title
    )

    authors: list[DimevAuthor] = []
    for author_node in record.xpath("./authors/author"):
        author = DimevAuthor(
            first=_child_text(author_node, "first"),
            last=_child_text(author_node, "last"),
            suffix=_child_text(author_node, "suffix"),
        )
        if author.display_name:
            authors.append(author)

    imev_id = None
    nimev_id = None
    for repertory in record.xpath("./repertories/repertory"):
        key = (repertory.get("key") or "").strip()
        value = _itertext_space(repertory)
        if not value:
            continue
        if key == "Brown1943":
            imev_id = value
        elif key == "NIMEV":
            nimev_id = value

    subjects: list[str] = []
    for subject_node in record.xpath("./subjects/subject"):
        subject = _itertext_space(subject_node)
        if subject and subject not in subjects:
            subjects.append(subject)

    first_lines: list[str] = []
    for first_line_node in record.xpath("./witnesses/witness/firstLines"):
        first_line = _strip_boundary_ellipsis(
            _line_break_text(first_line_node)
        )
        if first_line and first_line not in first_lines:
            first_lines.append(first_line)

    last_lines: list[str] = []
    for last_line_node in record.xpath("./witnesses/witness/lastLines"):
        last_line = _strip_boundary_ellipsis(_line_break_text(last_line_node))
        if last_line and last_line not in last_lines:
            last_lines.append(last_line)

    return DimevRecord(
        record_id=record_id,
        title=preferred_title,
        title_variants=title_variants,
        authors=tuple(authors),
        first_lines=tuple(first_lines),
        last_lines=tuple(last_lines),
        subjects=tuple(subjects),
        imev_id=imev_id,
        nimev_id=nimev_id,
    )


def _child_text(node: etree._Element, child_name: str) -> str | None:
    children = node.xpath(f"./{child_name}[1]")
    if not children:
        return None
    text = _itertext_space(children[0])
    return text or None


def _normalize_space(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def _itertext_space(node: etree._Element) -> str:
    parts = [part for part in (_normalize_space(text) for text in node.itertext()) if part]
    return " ".join(parts)


def _line_break_text(node: etree._Element) -> str:
    lines: list[str] = []
    current: list[str] = []

    def append_text(value: str | None) -> None:
        normalized = _normalize_space(value or "")
        if normalized:
            current.append(normalized)

    append_text(node.text)
    for child in node:
        if child.tag == "lb":
            lines.append(" ".join(current).strip())
            current = []
            append_text(child.tail)
            continue
        append_text("".join(child.itertext()))
        append_text(child.tail)

    final_line = " ".join(current).strip()
    if final_line or not lines:
        lines.append(final_line)
    return "\n".join(line for line in lines if line)


def _strip_boundary_ellipsis(text: str) -> str:
    stripped = text.strip()
    while True:
        updated = stripped.removeprefix("…").removeprefix("...").lstrip()
        updated = updated.removesuffix("…").removesuffix("...").rstrip()
        if updated == stripped:
            return updated
        stripped = updated


def default_cache_dir() -> Path:
    """Return the default on-disk cache directory for DIMEV data."""

    override = os.getenv("TEI_MSDESC_AUTHORITIES_CACHE_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "tei-msdesc-authorities"
    xdg_cache_home = os.getenv("XDG_CACHE_HOME")
    if xdg_cache_home:
        return Path(xdg_cache_home).expanduser() / "tei-msdesc-authorities"
    return Path.home() / ".cache" / "tei-msdesc-authorities"
