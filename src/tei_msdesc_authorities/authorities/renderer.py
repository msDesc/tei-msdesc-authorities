"""Catalogue-profile TEI rendering for authority records."""

from __future__ import annotations

import re
from dataclasses import dataclass
from xml.sax.saxutils import escape

from .models import EntityType, FloruitRange, LinkItem
from .records import (
    AuthorityRecordValue,
    OrgRecord,
    PersonRecord,
    PlaceRecord,
    WorkRecord,
)


def format_attrs(**attrs: str | None) -> str:
    """Render XML attributes in a stable order."""

    parts: list[str] = []
    for name in sorted(attrs.keys()):
        value = attrs[name]
        if value is None:
            continue
        parts.append(f' {name}="{escape(value)}"')
    return "".join(parts)


def floruit_certainty(floruit: FloruitRange | None) -> str | None:
    """Return a TEI certainty level for one floruit range."""

    if floruit is None:
        return None
    if (
        floruit.from_precision is not None
        and floruit.from_precision < 9
        or floruit.to_precision is not None
        and floruit.to_precision < 9
    ):
        return "low"
    return None


def display_date_suffix(record: PersonRecord) -> str | None:
    """Return the rendered date suffix for one person display label."""

    def format_display_life_date(value: str) -> str:
        if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
            return value[:4]
        return value

    def qualify(value: str, uncertain: bool) -> str:
        rendered = format_display_life_date(value)
        return f"{rendered}?" if uncertain else rendered

    if record.birth and record.death:
        return f"{qualify(record.birth, record.birth_uncertain)}–{qualify(record.death, record.death_uncertain)}"
    if record.death and not record.birth:
        return f"–{qualify(record.death, record.death_uncertain)}"
    if record.birth and not record.death:
        return f"{qualify(record.birth, record.birth_uncertain)}–"
    if (
        record.floruit
        and record.floruit.from_value
        and record.floruit.to_value
    ):
        return f"fl. {record.floruit.from_value}–{record.floruit.to_value}"
    if record.floruit and (
        record.floruit.from_value or record.floruit.to_value
    ):
        if record.floruit.from_value:
            return f"fl. {record.floruit.from_value}"
        if record.floruit.to_value:
            return f"fl. –{record.floruit.to_value}"
    return None


def display_label_for_person(record: PersonRecord) -> str:
    """Return the rendered display label for a person record."""

    suffix = display_date_suffix(record)
    return f"{record.label}, {suffix}" if suffix else record.label


def links_note_xml(links: tuple[LinkItem, ...], indent: str) -> list[str]:
    """Render a TEI links note for one authority entry."""

    if not links:
        return []
    lines = [f'{indent}<note type="links">', f'{indent}   <list type="links">']
    for link in links:
        lines.extend(
            [
                f"{indent}      <item>",
                f'{indent}         <ref target="{escape(link.target)}">',
                f"{indent}            <title>{escape(link.title)}</title>",
                f"{indent}         </ref>",
                f"{indent}      </item>",
            ]
        )
    lines.extend([f"{indent}   </list>", f"{indent}</note>"])
    return lines


def format_text_with_lbs(text: str) -> str:
    """Render multi-line text with TEI ``lb`` elements."""

    parts = [escape(part) for part in text.split("\n")]
    return "<lb/>".join(parts)


@dataclass(slots=True)
class CatalogueRenderer:
    """Base renderer for one catalogue profile."""


@dataclass(slots=True)
class MMOLTeiAuthorityRenderer(CatalogueRenderer):
    """Render canonical authority records into the current MMOL TEI shape."""

    def render(
        self, key: str, entity_type: EntityType, record: AuthorityRecordValue
    ) -> str:
        if entity_type == EntityType.PERSON:
            assert isinstance(record, PersonRecord)
            return self.render_person(key, record)
        if entity_type == EntityType.PLACE:
            assert isinstance(record, PlaceRecord)
            return self.render_place(key, record)
        if entity_type == EntityType.ORG:
            assert isinstance(record, OrgRecord)
            return self.render_org(key, record)
        assert isinstance(record, WorkRecord)
        return self.render_work(key, record)

    def display_label(self, record: AuthorityRecordValue) -> str:
        """Return the rendered display label used in reports."""

        if isinstance(record, PersonRecord):
            return display_label_for_person(record)
        return record.label

    def render_person(self, key: str, record: PersonRecord) -> str:
        lines = [f'            <person xml:id="{key}">']
        lines.append(
            f"               <persName{format_attrs(source=record.source.display_name, subtype=record.display_subtype, type='display')}>{escape(display_label_for_person(record))}</persName>"
        )
        for variant in record.variants:
            lines.append(
                f"               <persName{format_attrs(source=record.source.display_name, type='variant', **{'xml:lang': variant.lang})}>{escape(variant.value)}</persName>"
            )
        if record.birth:
            lines.append(
                f"               <birth{format_attrs(cert='medium' if record.birth_uncertain else None, source=record.source.display_name, when=record.birth)}/>"
            )
        if record.death:
            lines.append(
                f"               <death{format_attrs(cert='medium' if record.death_uncertain else None, source=record.source.display_name, when=record.death)}/>"
            )
        if record.floruit and (
            record.floruit.from_value or record.floruit.to_value
        ):
            lines.append(
                f"               <floruit{format_attrs(cert=floruit_certainty(record.floruit), **{'from': record.floruit.from_value, 'to': record.floruit.to_value})}/>"
            )
        if record.sex:
            lines.append(
                f"               <sex{format_attrs(source=record.source.display_name)}>{record.sex}</sex>"
            )
        for affiliation in record.affiliations:
            lines.append(
                f"               <affiliation{format_attrs(type=affiliation.relation_type)}><orgName{format_attrs(key=affiliation.key, source=record.source.display_name)}>{escape(affiliation.label)}</orgName></affiliation>"
            )
        for education in record.educations:
            lines.append(
                f"               <education><orgName{format_attrs(key=education.key, source=record.source.display_name)}>{escape(education.label)}</orgName></education>"
            )
        for nationality in record.nationalities:
            lines.append(
                f"               <nationality{format_attrs(key=nationality.key, source=record.source.display_name)}>{escape(nationality.label)}</nationality>"
            )
        for residence in record.residences:
            lines.append(
                f"               <residence><placeName{format_attrs(key=residence.key, source=record.source.display_name)}>{escape(residence.label)}</placeName></residence>"
            )
        for occupation in record.occupations:
            lines.append(
                f"               <occupation{format_attrs(source=record.source.display_name, **{'xml:lang': occupation.lang})}>{escape(occupation.value)}</occupation>"
            )
        lines.extend(links_note_xml(record.links, "               "))
        lines.append("            </person>")
        return "\n".join(lines)

    def render_place(self, key: str, record: PlaceRecord) -> str:
        lines = [
            f'            <place{format_attrs(type=record.place_type, **{"xml:id": key})}>'
        ]
        lines.append(
            f"               <placeName{format_attrs(source=record.source.display_name, type='index')}>{escape(record.label)}</placeName>"
        )
        for variant in record.variants:
            lines.append(
                f"               <placeName{format_attrs(source=record.source.display_name, type='variant', **{'xml:lang': variant.lang})}>{escape(variant.value)}</placeName>"
            )
        if record.coordinates:
            source_uri = record.source_ref
            if source_uri is None and record.source.source == "wikidata":
                source_uri = (
                    f"https://www.wikidata.org/entity/{record.source.identifier}"
                )
            if source_uri is None:
                source_uri = record.source.display_id
            lines.extend(
                [
                    f'               <location source="{escape(source_uri)}">',
                    f"                  <geo>{record.coordinates.latitude},{record.coordinates.longitude}</geo>",
                    "               </location>",
                ]
            )
        lines.extend(links_note_xml(record.links, "               "))
        lines.append("            </place>")
        return "\n".join(lines)

    def render_org(self, key: str, record: OrgRecord) -> str:
        lines = [f'            <org xml:id="{key}">']
        lines.append(
            f"               <orgName{format_attrs(source=record.source.display_name, type='display')}>{escape(record.label)}</orgName>"
        )
        for variant in record.variants:
            lines.append(
                f"               <orgName{format_attrs(source=record.source.display_name, type='variant', **{'xml:lang': variant.lang})}>{escape(variant.value)}</orgName>"
            )
        lines.extend(links_note_xml(record.links, "               "))
        lines.append("            </org>")
        return "\n".join(lines)

    def render_work(self, key: str, record: WorkRecord) -> str:
        lines = [f'            <bibl xml:id="{key}">']
        for author in record.authors:
            lines.append(
                f"               <author{format_attrs(key=author.key, source=author.source)}>{escape(author.label)}</author>"
            )
        uniform_parts: list[str] = []
        if record.authors:
            uniform_parts.append("; ".join(author.label for author in record.authors))
            uniform_parts.append(": ")
        uniform_parts.append(record.label)
        if record.main_lang_label:
            uniform_parts.append(f" [{record.main_lang_label}]")
        lines.append(
            f"               <title{format_attrs(source=record.source.display_name, type='uniform')}>{escape(''.join(uniform_parts))}</title>"
        )
        lines.append(
            f"               <title{format_attrs(source=record.source.display_name, type='primary')}>{escape(record.label)}</title>"
        )
        for variant in record.variants:
            lines.append(
                f"               <title{format_attrs(source=record.source.display_name, type='variant', **{'xml:lang': variant.lang})}>{escape(variant.value)}</title>"
            )
        lines.append(
            f'               <textLang mainLang="{escape(record.main_lang or "und")}"/>'
        )
        if record.incipit:
            lines.append(
                f"               <incipit{format_attrs(source=record.source.display_name, **{'xml:lang': record.incipit_lang})}>{format_text_with_lbs(record.incipit)}</incipit>"
            )
        for incipit in record.extra_incipits:
            lines.append(
                f"               <incipit{format_attrs(source=record.source.display_name, **{'xml:lang': record.incipit_lang})}>{format_text_with_lbs(incipit)}</incipit>"
            )
        for explicit in record.explicits:
            lines.append(
                f"               <explicit{format_attrs(source=record.source.display_name, **{'xml:lang': record.incipit_lang})}>{format_text_with_lbs(explicit)}</explicit>"
            )
        for subject in record.subjects:
            lines.append(
                f"               <term{format_attrs(source=record.source.display_name)}>{escape(subject)}</term>"
            )
        lines.extend(links_note_xml(record.links, "               "))
        lines.append("            </bibl>")
        return "\n".join(lines)
