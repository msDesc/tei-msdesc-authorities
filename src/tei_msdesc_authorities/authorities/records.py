"""Canonical authority record models.

These models represent the catalogue-facing shape of authority data before it
is rendered into any particular TEI serialization.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import (
    CoordinatePoint,
    EntityDetails,
    EntityType,
    ExternalIdentifier,
    FloruitRange,
    LinkedAuthorityRef,
    LinkItem,
    NameVariant,
    SourceRef,
    WorkAuthor,
)


@dataclass(slots=True, frozen=True)
class AuthorityRecord:
    """Canonical authority data shared across all entity types."""

    source: SourceRef
    label: str
    source_ref: str | None
    label_lang: str | None
    variants: tuple[NameVariant, ...]
    links: tuple[LinkItem, ...]
    external_identifiers: tuple[ExternalIdentifier, ...]


@dataclass(slots=True, frozen=True)
class PersonRecord(AuthorityRecord):
    """Canonical person authority data."""

    display_subtype: str | None
    honorific_prefix: str | None
    birth: str | None
    birth_uncertain: bool
    death: str | None
    death_uncertain: bool
    floruit: FloruitRange | None
    sex: str | None
    affiliations: tuple[LinkedAuthorityRef, ...]
    educations: tuple[LinkedAuthorityRef, ...]
    nationalities: tuple[LinkedAuthorityRef, ...]
    residences: tuple[LinkedAuthorityRef, ...]
    occupations: tuple[NameVariant, ...]


@dataclass(slots=True, frozen=True)
class PlaceRecord(AuthorityRecord):
    """Canonical place authority data."""

    coordinates: CoordinatePoint | None
    place_type: str | None


@dataclass(slots=True, frozen=True)
class OrgRecord(AuthorityRecord):
    """Canonical organization authority data."""


@dataclass(slots=True, frozen=True)
class WorkRecord(AuthorityRecord):
    """Canonical work authority data."""

    main_lang: str | None
    main_lang_label: str | None
    incipit: str | None
    incipit_lang: str | None
    extra_incipits: tuple[str, ...]
    explicits: tuple[str, ...]
    subjects: tuple[str, ...]
    authors: tuple[WorkAuthor, ...]


AuthorityRecordValue = PersonRecord | PlaceRecord | OrgRecord | WorkRecord


def record_from_details(
    entity_type: EntityType, details: EntityDetails
) -> AuthorityRecordValue:
    """Convert normalized source details into a canonical authority record."""

    common = {
        "source": details.source,
        "label": details.label,
        "source_ref": details.source_ref,
        "label_lang": details.label_lang,
        "variants": details.variants,
        "links": details.links,
        "external_identifiers": details.external_identifiers,
    }
    if entity_type == EntityType.PERSON:
        return PersonRecord(
            **common,
            display_subtype=details.display_subtype,
            honorific_prefix=details.honorific_prefix,
            birth=details.birth,
            birth_uncertain=details.birth_uncertain,
            death=details.death,
            death_uncertain=details.death_uncertain,
            floruit=details.floruit,
            sex=details.sex,
            affiliations=details.affiliations,
            educations=details.educations,
            nationalities=details.nationalities,
            residences=details.residences,
            occupations=details.occupations,
        )
    if entity_type == EntityType.PLACE:
        return PlaceRecord(
            **common,
            coordinates=details.coordinates,
            place_type=details.place_type,
        )
    if entity_type == EntityType.ORG:
        return OrgRecord(**common)
    return WorkRecord(
        **common,
        main_lang=details.main_lang,
        main_lang_label=details.main_lang_label,
        incipit=details.incipit,
        incipit_lang=details.incipit_lang,
        extra_incipits=details.extra_incipits,
        explicits=details.explicits,
        subjects=details.subjects,
        authors=details.authors,
    )
