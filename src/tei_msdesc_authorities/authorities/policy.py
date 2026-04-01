"""Catalogue profile policy for routing and local-key allocation."""

from __future__ import annotations

from dataclasses import dataclass

from .models import AuthorityListSpec, EntityType, ExternalIdentifier
from .records import AuthorityRecordValue, WorkRecord


def identifier_value(
    identifiers: tuple[ExternalIdentifier, ...], authority: str
) -> str | None:
    """Return the first identifier value for one authority namespace."""

    for identifier in identifiers:
        if identifier.authority == authority:
            return identifier.value
    return None


@dataclass(slots=True)
class CatalogueProfile:
    """Base catalogue profile policy."""


@dataclass(slots=True)
class MMOLCatalogueProfile(CatalogueProfile):
    """Apply Medieval Manuscripts in Oxford Libraries authority conventions.

    These rules are catalogue policy rather than source logic. In particular,
    VIAF, TGN, and GeoNames determine MMOL list routing and numeric local key
    allocation because the existing authority files are organized that way.
    """

    def route_record(
        self, entity_type: EntityType, record: AuthorityRecordValue
    ) -> AuthorityListSpec:
        if entity_type == EntityType.PLACE:
            if identifier_value(record.external_identifiers, "tgn"):
                return AuthorityListSpec("listPlace", "TGN", "place", "place")
            if identifier_value(record.external_identifiers, "geonames"):
                return AuthorityListSpec(
                    "listPlace", "geonames", "place", "place"
                )
            return AuthorityListSpec("listPlace", "local", "place", "place")

        if entity_type == EntityType.PERSON:
            if identifier_value(record.external_identifiers, "viaf"):
                return AuthorityListSpec(
                    "listPerson", "VIAF", "person", "person"
                )
            return AuthorityListSpec("listPerson", "local", "person", "person")

        if entity_type == EntityType.ORG:
            if identifier_value(record.external_identifiers, "viaf"):
                return AuthorityListSpec("listOrg", "VIAF", "org", "org")
            return AuthorityListSpec("listOrg", "local", "org", "org")

        work_record = record if isinstance(record, WorkRecord) else None
        if work_record is not None and work_record.authors:
            return AuthorityListSpec("listBibl", "authors", "bibl", "work")
        return AuthorityListSpec("listBibl", "anonymous", "bibl", "work")

    def assign_key(
        self,
        entity_type: EntityType,
        record: AuthorityRecordValue,
        used_ids: dict[str, set[int]],
        min_ids: dict[str, int],
    ) -> str:
        prefix = str(entity_type)

        explicit_id: str | None = None
        if entity_type in {EntityType.PERSON, EntityType.ORG}:
            explicit_id = identifier_value(record.external_identifiers, "viaf")
        elif entity_type == EntityType.PLACE:
            explicit_id = identifier_value(
                record.external_identifiers, "tgn"
            ) or identifier_value(record.external_identifiers, "geonames")

        if explicit_id is not None:
            numeric_id = int(explicit_id)
            if numeric_id in used_ids[prefix]:
                raise ValueError(
                    f"Cannot create {prefix}_{numeric_id}: numeric ID already exists in authority file"
                )
            used_ids[prefix].add(numeric_id)
            return f"{prefix}_{numeric_id}"

        return f"{prefix}_{self.next_available_id(used_ids[prefix], min_ids[prefix])}"

    @staticmethod
    def next_available_id(used: set[int], min_id: int) -> int:
        """Allocate the next available numeric local identifier."""

        candidate = max(1, min_id)
        while candidate in used:
            candidate += 1
        used.add(candidate)
        return candidate
