"""Application services for authority planning."""

from __future__ import annotations

from dataclasses import dataclass

from .models import EntityDetails, EntityType, PlannedEntry
from .policy import CatalogueProfile
from .records import record_from_details
from .renderer import CatalogueRenderer


@dataclass(slots=True)
class AuthorityEntryPlanner:
    """Plan authority entries for one catalogue profile."""

    policy: CatalogueProfile
    renderer: CatalogueRenderer

    def plan_entry(
        self,
        entity_type: EntityType,
        details: EntityDetails,
        used_ids: dict[str, set[int]],
        min_ids: dict[str, int],
    ) -> PlannedEntry:
        """Route, key, and render one planned authority entry."""

        record = record_from_details(entity_type, details)
        list_spec = self.policy.route_record(entity_type, record)
        key = self.policy.assign_key(entity_type, record, used_ids, min_ids)
        return PlannedEntry(
            source=details.source,
            key=key,
            entity_type=entity_type,
            label=self.renderer.display_label(record),
            list_spec=list_spec,
            external_identifiers=details.external_identifiers,
            xml_snippet=self.renderer.render(key, entity_type, record),
        )
