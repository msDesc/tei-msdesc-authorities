from __future__ import annotations

from pathlib import Path


def test_insert_entries_in_numeric_order_handles_viaf_list(
    module, tmp_path: Path
) -> None:
    path = tmp_path / "persons.xml"
    path.write_text(
        """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><listPerson type="VIAF">
            <person xml:id="person_100">
               <persName type="display">Earlier</persName>
            </person>
            <person xml:id="person_300">
               <persName type="display">Later</persName>
            </person>
            </listPerson></body></text></TEI>""",
        encoding="utf-8",
    )
    entry = module.PlannedEntry(
        source=module.SourceRef("wikidata", "Q200", "Wikidata"),
        key="person_200",
        entity_type="person",
        label="Inserted",
        list_spec=module.AuthorityListSpec(
            "listPerson", "VIAF", "person", "person"
        ),
        external_identifiers=(module.ExternalIdentifier("viaf", "200"),),
        xml_snippet='            <person xml:id="person_200">\n               <persName type="display">Inserted</persName>\n            </person>',
    )

    module.insert_entries_in_numeric_order(
        path, "listPerson", "VIAF", "person", "person", [entry]
    )

    updated = path.read_text(encoding="utf-8")
    assert (
        updated.index('xml:id="person_100"')
        < updated.index('xml:id="person_200"')
        < updated.index('xml:id="person_300"')
    )


def test_insert_entries_in_numeric_order_handles_tgn_list(
    module, tmp_path: Path
) -> None:
    path = tmp_path / "places.xml"
    path.write_text(
        """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><listPlace type="TGN">
            <place xml:id="place_100">
               <placeName type="index">Earlier</placeName>
            </place>
            <place xml:id="place_300">
               <placeName type="index">Later</placeName>
            </place>
            </listPlace></body></text></TEI>""",
        encoding="utf-8",
    )
    entry = module.PlannedEntry(
        source=module.SourceRef("wikidata", "Q200", "Wikidata"),
        key="place_200",
        entity_type="place",
        label="Inserted",
        list_spec=module.AuthorityListSpec(
            "listPlace", "TGN", "place", "place"
        ),
        external_identifiers=(module.ExternalIdentifier("tgn", "200"),),
        xml_snippet='            <place xml:id="place_200">\n               <placeName type="index">Inserted</placeName>\n            </place>',
    )

    module.insert_entries_in_numeric_order(
        path, "listPlace", "TGN", "place", "place", [entry]
    )

    updated = path.read_text(encoding="utf-8")
    assert (
        updated.index('xml:id="place_100"')
        < updated.index('xml:id="place_200"')
        < updated.index('xml:id="place_300"')
    )


def test_insert_entries_in_numeric_order_reindents_to_match_tgn_list(
    module, tmp_path: Path
) -> None:
    path = tmp_path / "places.xml"
    path.write_text(
        """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><listPlace type="TGN">
           <place xml:id="place_100" type="settlement">
              <placeName type="index">Earlier</placeName>
           </place>
           <place xml:id="place_300" type="settlement">
              <placeName type="index">Later</placeName>
           </place>
         </listPlace></body></text></TEI>""",
        encoding="utf-8",
    )
    entry = module.PlannedEntry(
        source=module.SourceRef("wikidata", "Q200", "Wikidata"),
        key="place_200",
        entity_type="place",
        label="Inserted",
        list_spec=module.AuthorityListSpec(
            "listPlace", "TGN", "place", "place"
        ),
        external_identifiers=(module.ExternalIdentifier("tgn", "200"),),
        xml_snippet='            <place xml:id="place_200">\n               <placeName type="index">Inserted</placeName>\n            </place>',
    )

    module.insert_entries_in_numeric_order(
        path, "listPlace", "TGN", "place", "place", [entry]
    )

    updated = path.read_text(encoding="utf-8")
    assert '\n           <place xml:id="place_200">' in updated
    assert (
        '\n              <placeName type="index">Inserted</placeName>'
        in updated
    )
    assert '\n                      <place xml:id="place_200">' not in updated


def test_insert_entries_in_numeric_order_ignores_commented_tgn_entries_for_indent(
    module, tmp_path: Path
) -> None:
    path = tmp_path / "places.xml"
    path.write_text(
        """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><listPlace type="TGN">
            <!--<place type="settlement" xml:id="place_10">
               <placeName type="index">Commented</placeName>
            </place>-->
            <place type="settlement" xml:id="place_100">
               <placeName type="index">Earlier</placeName>
            </place>
            </listPlace></body></text></TEI>""",
        encoding="utf-8",
    )
    entry = module.PlannedEntry(
        source=module.SourceRef("wikidata", "Q200", "Wikidata"),
        key="place_200",
        entity_type="place",
        label="Inserted",
        list_spec=module.AuthorityListSpec(
            "listPlace", "TGN", "place", "place"
        ),
        external_identifiers=(module.ExternalIdentifier("tgn", "200"),),
        xml_snippet='            <place xml:id="place_200">\n               <placeName type="index">Inserted</placeName>\n            </place>',
    )

    module.insert_entries_in_numeric_order(
        path, "listPlace", "TGN", "place", "place", [entry]
    )

    updated = path.read_text(encoding="utf-8")
    assert '\n            <place xml:id="place_200">' in updated
    assert "\n            </listPlace>" in updated
    assert '\n<place xml:id="place_200">' not in updated


def test_insert_entries_in_numeric_order_handles_irregular_local_org_list(
    module, tmp_path: Path
) -> None:
    path = tmp_path / "places.xml"
    path.write_text(
        """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><listOrg type="local">
            <org xml:id="org_124557775">
               <orgName type="display">Outlier</orgName>
            </org>
            <org xml:id="org_378">
               <orgName type="display">Earlier</orgName>
            </org>
            <org xml:id="org_380">
               <orgName type="display">Later</orgName>
            </org>
            </listOrg></body></text></TEI>""",
        encoding="utf-8",
    )
    entry = module.PlannedEntry(
        source=module.SourceRef("wikidata", "Q381", "Wikidata"),
        key="org_381",
        entity_type="org",
        label="Inserted",
        list_spec=module.AuthorityListSpec("listOrg", "local", "org", "org"),
        external_identifiers=(),
        xml_snippet='            <org xml:id="org_381">\n               <orgName type="display">Inserted</orgName>\n            </org>',
    )

    module.insert_entries_in_numeric_order(
        path, "listOrg", "local", "org", "org", [entry]
    )

    updated = path.read_text(encoding="utf-8")
    assert updated.index('xml:id="org_380"') < updated.index('xml:id="org_381"')
