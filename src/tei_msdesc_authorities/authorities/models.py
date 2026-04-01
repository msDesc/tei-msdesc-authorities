"""Shared constants, enums, and data models for authority workflows."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

NS = {
    "tei": "http://www.tei-c.org/ns/1.0",
    "xml": "http://www.w3.org/XML/1998/namespace",
}
BARE_QID_RE = re.compile(r"^Q\d+$", re.IGNORECASE)
ID_RE = re.compile(r"^(person|place|org|work)_(\d+)$")
WIKIDATA_ENTITY_PATH_RE = re.compile(
    r"^/(?:entity|wiki)/(Q\d+)$", re.IGNORECASE
)
WIKIDATA_ENTITY_DATA_PATH_RE = re.compile(
    r"^/wiki/Special:EntityData/(Q\d+)(?:\.[A-Za-z0-9]+)?$", re.IGNORECASE
)
VIAF_PATH_RE = re.compile(r"^/(?:en/)?viaf/(\d+)(?:/.*)?$", re.IGNORECASE)


class Command(StrEnum):
    """Top-level CLI subcommands."""

    ENRICH = "enrich"
    RECONCILE = "reconcile"
    REGENERATE = "regenerate"


class ElementName(StrEnum):
    """Supported TEI element names that can carry unresolved external refs."""

    AUTHOR = "author"
    PERS_NAME = "persName"
    PLACE_NAME = "placeName"
    COUNTRY = "country"
    ORG_NAME = "orgName"
    TITLE = "title"


class EntityType(StrEnum):
    """Authority record types managed by the package."""

    PERSON = "person"
    PLACE = "place"
    ORG = "org"
    WORK = "work"


@dataclass(slots=True, frozen=True)
class SourceRef:
    """A normalized external source reference.

    ``source`` is a stable internal key such as ``wikidata`` or ``dimev``.
    ``identifier`` is the source-local identifier without additional prefixing.
    """

    source: str
    identifier: str
    source_name: str | None = None

    @property
    def lookup_key(self) -> str:
        """Return the normalized key used for local source-to-authority lookups."""

        return f"{self.source}:{self.identifier}"

    @property
    def display_id(self) -> str:
        """Return the user-facing source identifier string."""

        if self.source == "wikidata":
            return self.identifier
        return f"{self.source.upper()}:{self.identifier}"

    @property
    def display_name(self) -> str:
        """Return the human-readable source name."""

        if self.source_name:
            return self.source_name
        return self.source.replace("_", " ").title()


@dataclass(slots=True, frozen=True)
class SourceTarget:
    """A source ref requested by a workflow, optionally with a forced entity type."""

    entity_type: EntityType | None
    ref: SourceRef

    @property
    def source(self) -> str:
        return self.ref.source

    @property
    def identifier(self) -> str:
        return self.ref.identifier

    @property
    def lookup_key(self) -> str:
        return self.ref.lookup_key

    @property
    def display_id(self) -> str:
        return self.ref.display_id


type EnsureRelatedFn = Callable[[EntityType, str, str], tuple[str, str]]
type EnsurePersonFn = Callable[
    [str | None, str | None, str | None], tuple[str, str, str | None]
]

XPATH_CANDIDATES = (
    "//tei:author[@ref and not(@key)]"
    " | //tei:persName[@ref and not(@key)]"
    " | //tei:placeName[@ref and not(@key)]"
    " | //tei:country[@ref and not(@key)]"
    " | //tei:orgName[@ref and not(@key)]"
    " | //tei:title[@ref and not(@key)]"
)

PERSON_ID_LINKS = [
    ("P214", "VIAF", "https://viaf.org/viaf/{value}"),
    ("P227", "Deutsche Nationalbibliothek", "https://d-nb.info/gnd/{value}"),
    (
        "P244",
        "Library of Congress",
        "http://id.loc.gov/authorities/names/{value}",
    ),
    ("P213", "ISNI", "http://www.isni.org/isni/{value}"),
    (
        "P268",
        "Bibliothèque nationale de France",
        "https://catalogue.bnf.fr/ark:/12148/cb{value}",
    ),
    ("P2163", "FAST", "https://id.worldcat.org/fast/{value}"),
    ("P269", "SUDOC", "https://www.idref.fr/{value}"),
]

PLACE_ID_LINKS = [
    ("P1566", "GeoNames", "https://www.geonames.org/{value}"),
    ("P1667", "Getty TGN", "http://vocab.getty.edu/tgn/{value}"),
    ("P214", "VIAF", "https://viaf.org/viaf/{value}"),
    ("P227", "Deutsche Nationalbibliothek", "https://d-nb.info/gnd/{value}"),
]

WORK_ID_LINKS = [
    ("P214", "VIAF", "https://viaf.org/viaf/{value}"),
    (
        "P244",
        "Library of Congress",
        "http://id.loc.gov/authorities/names/{value}",
    ),
    (
        "P268",
        "Bibliothèque nationale de France",
        "https://catalogue.bnf.fr/ark:/12148/cb{value}",
    ),
]

KNOWN_LINK_TITLES = {
    "P1415": "Oxford Dictionary of National Biography",
    "P4549": "ARLIMA",
    "P214": "VIAF",
    "P227": "Deutsche Nationalbibliothek",
    "P244": "Library of Congress",
    "P213": "ISNI",
    "P268": "Bibliothèque nationale de France",
    "P2163": "FAST",
    "P269": "SUDOC",
    "P1566": "GeoNames",
    "P1667": "Getty TGN",
}

SUPPRESSED_LINK_PROPERTIES = {
    "P2671",
    "P9015",
    "P9016",
    "P9017",
    "P9018",
    "P9019",
}
TRUSTED_PROPERTY_CLASS_QIDS = {
    "Q97584729",  # property related to biographical dictionaries
    "Q56248867",  # property related to the Middle Ages
    "Q96192295",  # property widely reused by third-party entities
    "Q55452870",  # property related to authority control
    "Q29547399",  # property to identify books
    "Q29546563",  # property for items about manuscripts
}
LOCAL_AUTHORITY_EQUIVALENTS: dict[tuple[str, str], str] = {
    # Editorially controlled equivalences used to reuse an existing local
    # authority rather than creating near-duplicate historical variants.
    ("place", "Q179876"): "place_7002445",  # Kingdom of England -> England
    ("place", "Q330362"): "place_7002445",  # Commonwealth of England -> England
    (
        "place",
        "Q161885",
    ): "place_7008591",  # Kingdom of Great Britain -> United Kingdom
    (
        "place",
        "Q174193",
    ): "place_7008591",  # United Kingdom of Great Britain and Ireland -> United Kingdom
}

SEX_MAP = {
    "Q6581097": "male",
    "Q6581072": "female",
    "Q1097630": "intersex",
}

SETTLEMENT_TYPE_QIDS = {
    "Q486972",  # human settlement
    "Q515",  # city
    "Q3957",  # town
    "Q532",  # village
}
COUNTRY_TYPE_QIDS = {
    "Q6256",  # country
    "Q3024240",  # historical country
}
REGION_TYPE_QIDS = {
    "Q82794",  # geographic region
    "Q16110",  # region
    "Q35657",  # state
}


def element_to_entity(local: str) -> EntityType | None:
    """Map a TEI local element name to the corresponding authority type."""

    return {
        "author": EntityType.PERSON,
        "persName": EntityType.PERSON,
        "placeName": EntityType.PLACE,
        "country": EntityType.PLACE,
        "orgName": EntityType.ORG,
        "title": EntityType.WORK,
    }.get(local)


def entity_to_prefix(entity_type: EntityType) -> str:
    """Return the local key prefix for an authority entity type."""

    return entity_type


@dataclass(slots=True, frozen=True)
class Candidate:
    """An unresolved manuscript reference that may need a local authority key."""

    file_path: Path
    element_name: ElementName
    entity_type: EntityType
    ref: str
    source: SourceRef
    text: str
    context_author_key: str | None = None
    context_author_text: str | None = None

    @property
    def source_id(self) -> str:
        """Return the legacy display form of the primary source identifier."""

        return self.source.display_id


@dataclass(slots=True, frozen=True)
class LinkItem:
    """A rendered external link destined for a TEI ``note[@type='links']``."""

    title: str
    target: str


@dataclass(slots=True, frozen=True)
class NameVariant:
    """An alternative label or alias for an authority entry."""

    value: str
    lang: str | None = None


@dataclass(slots=True, frozen=True)
class WorkAuthor:
    """Resolved author information for a generated work authority record."""

    key: str | None
    label: str
    source: str | None = None


@dataclass(slots=True, frozen=True)
class LinkedAuthorityRef:
    """A resolved local authority reference linked from another entity."""

    key: str
    label: str
    relation_type: str | None = None


@dataclass(slots=True, frozen=True)
class ExternalIdentifier:
    """An external identifier preserved as catalogue policy input."""

    authority: str
    value: str


@dataclass(slots=True, frozen=True)
class AuthorityListSpec:
    """The target TEI list into which a new authority record should be inserted."""

    list_tag: str
    list_type: str
    child_tag: str
    prefix: str


@dataclass(slots=True, frozen=True)
class FloruitRange:
    """Normalized floruit bounds together with their source precision."""

    from_value: str | None = None
    to_value: str | None = None
    from_precision: int | None = None
    to_precision: int | None = None


@dataclass(slots=True, frozen=True)
class CoordinatePoint:
    """A serialized coordinate pair ready for TEI ``geo`` output."""

    latitude: str
    longitude: str


@dataclass(slots=True, frozen=True)
class ClaimValue:
    """A thin wrapper around a raw Wikidata claim value."""

    raw: object

    def as_mapping(self) -> dict[str, object] | None:
        return self.raw if isinstance(self.raw, dict) else None

    def as_string(self) -> str | None:
        return (
            self.raw.strip()
            if isinstance(self.raw, str) and self.raw.strip()
            else None
        )

    def entity_id(self) -> str | None:
        mapping = self.as_mapping()
        if not mapping:
            return None
        entity_id = mapping.get("id")
        return (
            entity_id
            if isinstance(entity_id, str) and entity_id.startswith("Q")
            else None
        )

    def monolingual_text(self) -> tuple[str, str | None] | None:
        mapping = self.as_mapping()
        if not mapping:
            return None
        text = mapping.get("text")
        lang = mapping.get("language")
        if isinstance(text, str) and text.strip():
            return text.strip(), lang if isinstance(lang, str) else None
        return None


@dataclass(slots=True, frozen=True)
class ClaimStatement:
    """A parsed Wikidata statement with its value and qualifier QIDs."""

    mainsnak_value: ClaimValue | None
    qualifiers: dict[str, tuple[ClaimValue, ...]]

    def qualifier_entity_ids(self, pid: str) -> tuple[str, ...]:
        result: list[str] = []
        for qualifier in self.qualifiers.get(pid, ()):
            entity_id = qualifier.entity_id()
            if entity_id and entity_id not in result:
                result.append(entity_id)
        return tuple(result)


@dataclass(slots=True, frozen=True)
class EntityDetails:
    """Normalized external-source data ready for TEI serialization."""

    source: SourceRef
    label: str
    source_ref: str | None = None
    label_lang: str | None = None
    display_subtype: str | None = None
    honorific_prefix: str | None = None
    variants: tuple[NameVariant, ...] = ()
    birth: str | None = None
    birth_uncertain: bool = False
    death: str | None = None
    death_uncertain: bool = False
    floruit: FloruitRange | None = None
    sex: str | None = None
    links: tuple[LinkItem, ...] = ()
    coordinates: CoordinatePoint | None = None
    place_type: str | None = None
    main_lang: str | None = None
    main_lang_label: str | None = None
    incipit: str | None = None
    incipit_lang: str | None = None
    extra_incipits: tuple[str, ...] = ()
    explicits: tuple[str, ...] = ()
    subjects: tuple[str, ...] = ()
    authors: tuple[WorkAuthor, ...] = ()
    affiliations: tuple[LinkedAuthorityRef, ...] = ()
    educations: tuple[LinkedAuthorityRef, ...] = ()
    nationalities: tuple[LinkedAuthorityRef, ...] = ()
    residences: tuple[LinkedAuthorityRef, ...] = ()
    occupations: tuple[NameVariant, ...] = ()
    external_identifiers: tuple[ExternalIdentifier, ...] = ()

    @property
    def source_id(self) -> str:
        """Return the legacy display form of the primary source identifier."""

        return self.source.display_id

    @property
    def source_name(self) -> str:
        """Return the human-readable source name used in generated TEI."""

        return self.source.display_name


@dataclass(slots=True, frozen=True)
class PlannedEntry:
    """A prepared authority record that has not yet been inserted into XML."""

    source: SourceRef
    key: str
    entity_type: EntityType
    label: str
    list_spec: AuthorityListSpec
    external_identifiers: tuple[ExternalIdentifier, ...]
    xml_snippet: str

    @property
    def source_id(self) -> str:
        """Return the legacy display form of the primary source identifier."""

        return self.source.display_id


@dataclass(slots=True, frozen=True)
class PersonAuthorityRecord:
    """Local person authority data used during reconciliation and reuse."""

    key: str
    display_label: str | None = None
    variant_labels: tuple[str, ...] = ()
    wikidata_qids: frozenset[str] = frozenset()
    viaf_ids: frozenset[str] = frozenset()


@dataclass(slots=True, frozen=True)
class ExistingPersonEntry:
    """A parsed existing local person authority entry."""

    key: str
    line: int | None
    display_label: str
    query_label: str
    wikidata_qids: frozenset[str]
    viaf_ids: frozenset[str]
    birth: str | None = None
    death: str | None = None
    floruit: FloruitRange | None = None


@dataclass(slots=True, frozen=True)
class DuplicateIdentifierIssue:
    """A duplicate identifier discovered during authority validation."""

    authority_path: Path
    identifier_type: str
    identifier_value: str
    keys: tuple[str, ...]
    locations: tuple[tuple[str, int | None], ...]
