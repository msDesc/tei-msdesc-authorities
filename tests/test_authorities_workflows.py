from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


def test_regenerate_person_with_related_entities_replaces_person_entry(
    module, client, tmp_path: Path
) -> None:
    client._entity_cache.update(
        {
            "QPERSON": {
                "labels": {"en": {"value": "John Example"}},
                "claims": {
                    "P735": [
                        {"mainsnak": {"datavalue": {"value": {"id": "QGIVEN"}}}}
                    ],
                    "P734": [
                        {
                            "mainsnak": {
                                "datavalue": {"value": {"id": "QFAMILY"}}
                            }
                        }
                    ],
                    "P611": [
                        {"mainsnak": {"datavalue": {"value": {"id": "QORDER"}}}}
                    ],
                    "P551": [
                        {"mainsnak": {"datavalue": {"value": {"id": "QPLACE"}}}}
                    ],
                },
            },
            "QGIVEN": {"labels": {"en": {"value": "John"}}},
            "QFAMILY": {"labels": {"en": {"value": "Example"}}},
            "QORDER": {
                "labels": {"en": {"value": "Order of Preachers"}},
                "claims": {},
            },
            "QPLACE": {"labels": {"en": {"value": "Paris"}}, "claims": {}},
        }
    )
    persons = tmp_path / "persons.xml"
    places = tmp_path / "places.xml"
    works = tmp_path / "works.xml"
    persons.write_text(
        """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><listPerson type="local">
            <person xml:id="person_4803">
               <persName type="display">Old Label</persName>
               <note type="links"><list type="links"><item><ref target="https://www.wikidata.org/entity/QPERSON"><title>Wikidata</title></ref></item></list></note>
            </person>
            </listPerson></body></text></TEI>""",
        encoding="utf-8",
    )
    places.write_text(
        """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>
            <listPlace type="local"></listPlace>
            <listOrg type="local"></listOrg>
            </body></text></TEI>""",
        encoding="utf-8",
    )
    works.write_text(
        """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><listBibl type="anonymous"></listBibl></body></text></TEI>""",
        encoding="utf-8",
    )

    path, entity_type, created_related = module.regenerate_entry(
        "person_4803",
        "QPERSON",
        persons_path=persons,
        places_path=places,
        works_path=works,
        client=client,
        min_ids={"person": 1, "place": 1, "org": 1, "work": 1},
    )

    updated = persons.read_text(encoding="utf-8")
    assert path == persons
    assert entity_type == "person"
    assert sorted(
        (entry.entity_type, entry.key) for entry in created_related
    ) == [
        ("org", "org_1"),
        ("place", "place_1"),
    ]
    assert 'xml:id="person_4803"' in updated
    assert "Example, John" in updated


def test_main_regenerates_every_entry(
    monkeypatch, capsys, module, cli_module, core_module
) -> None:
    persons = Path("persons.xml")
    places = Path("places.xml")
    works = Path("works.xml")
    requested = [
        "person_4803",
        "person_4805",
        "person_4815",
        "person_4816",
        "person_4817",
    ]
    qids = {key: f"Q{index}" for index, key in enumerate(requested, start=1)}
    calls: list[tuple[str, str]] = []
    state = module.RegenerationState(
        existing_person_qid_map={},
        existing_place_qid_map={},
        existing_org_qid_map={},
        person_display_map={},
        place_display_map={},
        org_display_map={},
        used_ids={"person": set(), "place": set(), "org": set(), "work": set()},
    )
    load_calls = 0

    monkeypatch.setattr(
        cli_module,
        "parse_args",
        lambda _argv=None: SimpleNamespace(
            command="regenerate",
            dry_run=False,
            no_fetch=True,
            entries=requested,
            persons=persons,
            places=places,
            works=works,
            person_min_id=1,
            place_min_id=1,
            org_min_id=1,
            work_min_id=1,
            reconcile_limit=5,
            report=Path("processing/authority_enrichment_report.json"),
            inputs=[],
            keep_ref=False,
            handler=core_module.run_regenerate,
        ),
    )
    monkeypatch.setattr(
        core_module,
        "authority_file_for_key",
        lambda key, *_: (persons, "person", "person"),
    )
    monkeypatch.setattr(
        core_module,
        "existing_entry_wikidata_qid",
        lambda _path, key, _child_tag: qids[key],
    )

    def fake_load(**_kwargs: object) -> object:
        nonlocal load_calls
        load_calls += 1
        return state

    monkeypatch.setattr(
        core_module.RegenerationState,
        "load",
        classmethod(lambda cls, **kwargs: fake_load(**kwargs)),
    )

    def fake_regenerate_entry(
        key: str, qid: str, **_kwargs: object
    ) -> tuple[Path, str, tuple[object, ...]]:
        calls.append((key, qid))
        assert _kwargs["regeneration_state"] is state
        return persons, "person", ()

    monkeypatch.setattr(core_module, "regenerate_entry", fake_regenerate_entry)

    assert cli_module.main() == 0
    assert load_calls == 1
    assert calls == [(key, qids[key]) for key in requested]
    output = capsys.readouterr().out
    for key in requested:
        assert f"{key} <- {qids[key]} (person)" in output


def test_main_reports_created_related_entries_during_regeneration(
    monkeypatch, capsys, module, cli_module, core_module
) -> None:
    persons = Path("persons.xml")
    places = Path("places.xml")
    works = Path("works.xml")
    monkeypatch.setattr(
        cli_module,
        "parse_args",
        lambda _argv=None: SimpleNamespace(
            command="regenerate",
            dry_run=False,
            no_fetch=True,
            entries=["person_4816"],
            persons=persons,
            places=places,
            works=works,
            person_min_id=1,
            place_min_id=1,
            org_min_id=1,
            work_min_id=1,
            reconcile_limit=5,
            report=Path("processing/authority_enrichment_report.json"),
            inputs=[],
            keep_ref=False,
            handler=core_module.run_regenerate,
        ),
    )
    monkeypatch.setattr(
        core_module,
        "authority_file_for_key",
        lambda key, *_: (persons, "person", "person"),
    )
    monkeypatch.setattr(
        core_module,
        "existing_entry_wikidata_qid",
        lambda _path, _key, _child_tag: "Q4816",
    )
    monkeypatch.setattr(
        core_module.RegenerationState,
        "load",
        classmethod(
            lambda cls, **_kwargs: module.RegenerationState(
                existing_person_qid_map={},
                existing_place_qid_map={},
                existing_org_qid_map={},
                person_display_map={},
                place_display_map={},
                org_display_map={},
                used_ids={
                    "person": set(),
                    "place": set(),
                    "org": set(),
                    "work": set(),
                },
            )
        ),
    )
    monkeypatch.setattr(
        core_module,
        "regenerate_entry",
        lambda key, qid, **_kwargs: (
            persons,
            "person",
            (
                module.PlannedEntry(
                    qid="QORG",
                    key="org_123",
                    entity_type="org",
                    label="Cirencester Abbey",
                    list_spec=module.AuthorityListSpec(
                        "listOrg", "local", "org", "org"
                    ),
                    external_ids=module.ExternalAuthorityIds(),
                    xml_snippet="<org/>",
                ),
                module.PlannedEntry(
                    qid="QPLACE",
                    key="place_456",
                    entity_type="place",
                    label="England",
                    list_spec=module.AuthorityListSpec(
                        "listPlace", "local", "place", "place"
                    ),
                    external_ids=module.ExternalAuthorityIds(),
                    xml_snippet="<place/>",
                ),
            ),
        ),
    )

    assert cli_module.main() == 0
    output = capsys.readouterr().out
    assert "persons.xml: regenerated person_4816 <- Q4816 (person)" in output
    assert (
        "places.xml: created related org_123 <- QORG (org: Cirencester Abbey) for person_4816"
        in output
    )
    assert (
        "places.xml: created related place_456 <- QPLACE (place: England) for person_4816"
        in output
    )


def test_run_enrich_applies_person_entry_and_manuscript_key_update(
    module, client, tmp_path: Path, capsys
) -> None:
    persons = tmp_path / "persons.xml"
    places = tmp_path / "places.xml"
    works = tmp_path / "works.xml"
    manuscript = tmp_path / "manuscript.xml"
    report = tmp_path / "report.json"

    persons.write_text(
        """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><listPerson type="local">
            <person xml:id="person_1">
               <persName type="display">Existing Person</persName>
            </person>
            </listPerson></body></text></TEI>""",
        encoding="utf-8",
    )
    places.write_text(
        """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>
            <listPlace type="local"></listPlace>
            <listOrg type="local"></listOrg>
            </body></text></TEI>""",
        encoding="utf-8",
    )
    works.write_text(
        """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>
            <listBibl type="authors"></listBibl>
            <listBibl type="anonymous"></listBibl>
            </body></text></TEI>""",
        encoding="utf-8",
    )
    manuscript.write_text(
        """<TEI xml:id="manuscript_1" xmlns="http://www.tei-c.org/ns/1.0"><text><body><msDesc><msContents><msItem>
                <persName ref="https://www.wikidata.org/entity/Q12345">John Example</persName>
            </msItem></msContents></msDesc></body></text></TEI>""",
        encoding="utf-8",
    )

    args = SimpleNamespace(
        command="enrich",
        dry_run=False,
        keep_ref=False,
        inputs=[str(manuscript)],
        persons=persons,
        places=places,
        works=works,
        report=report,
        no_fetch=True,
        person_min_id=1,
        place_min_id=1,
        org_min_id=1,
        work_min_id=1,
    )

    assert module.run_enrich(args, client) == 0

    updated_persons = persons.read_text(encoding="utf-8")
    updated_manuscript = manuscript.read_text(encoding="utf-8")
    payload = module.json.loads(report.read_text(encoding="utf-8"))
    output = capsys.readouterr().out

    assert 'xml:id="person_2"' in updated_persons
    assert ">John Example</persName>" in updated_persons
    assert "https://www.wikidata.org/entity/Q12345" in updated_persons
    assert (
        '<persName key="person_2">John Example</persName>' in updated_manuscript
    )
    assert (
        'ref="https://www.wikidata.org/entity/Q12345"' not in updated_manuscript
    )
    assert payload["candidate_count"] == 1
    assert payload["new_entries"][0]["key"] == "person_2"
    assert payload["manuscript_updates"][0]["assigned_key"] == "person_2"
    assert "Applied manuscript updates in 1 file(s)" in output


def test_run_enrich_applies_author_ref_as_person_key_update(
    module, client, tmp_path: Path, capsys
) -> None:
    persons = tmp_path / "persons.xml"
    places = tmp_path / "places.xml"
    works = tmp_path / "works.xml"
    manuscript = tmp_path / "manuscript.xml"
    report = tmp_path / "report.json"

    persons.write_text(
        """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><listPerson type="local"></listPerson></body></text></TEI>""",
        encoding="utf-8",
    )
    places.write_text(
        """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><listPlace type="local"></listPlace><listOrg type="local"></listOrg></body></text></TEI>""",
        encoding="utf-8",
    )
    works.write_text(
        """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><listBibl type="authors"></listBibl><listBibl type="anonymous"></listBibl></body></text></TEI>""",
        encoding="utf-8",
    )
    manuscript.write_text(
        """<TEI xml:id="manuscript_1" xmlns="http://www.tei-c.org/ns/1.0"><text><body><msDesc><msContents><msItem><author ref="https://www.wikidata.org/wiki/Q316090">Valerius Flaccus</author></msItem></msContents></msDesc></body></text></TEI>""",
        encoding="utf-8",
    )

    args = SimpleNamespace(
        command="enrich",
        dry_run=False,
        keep_ref=False,
        inputs=[str(manuscript)],
        persons=persons,
        places=places,
        works=works,
        report=report,
        no_fetch=True,
        person_min_id=1,
        place_min_id=1,
        org_min_id=1,
        work_min_id=1,
    )

    assert module.run_enrich(args, client) == 0

    updated_persons = persons.read_text(encoding="utf-8")
    updated_manuscript = manuscript.read_text(encoding="utf-8")
    payload = module.json.loads(report.read_text(encoding="utf-8"))
    output = capsys.readouterr().out

    assert 'xml:id="person_1"' in updated_persons
    assert ">Valerius Flaccus</persName>" in updated_persons
    assert "Q316090" in updated_persons
    assert (
        '<author key="person_1">Valerius Flaccus</author>'
        in updated_manuscript
    )
    assert 'ref="https://www.wikidata.org/wiki/Q316090"' not in updated_manuscript
    assert payload["candidate_count"] == 1
    assert payload["new_entries"][0]["key"] == "person_1"
    assert payload["manuscript_updates"][0]["element"] == "author"
    assert payload["manuscript_updates"][0]["assigned_key"] == "person_1"
    assert "Applied manuscript updates in 1 file(s)" in output


def test_run_enrich_dry_run_leaves_files_unchanged_but_writes_report(
    module, client, tmp_path: Path, capsys
) -> None:
    persons = tmp_path / "persons.xml"
    places = tmp_path / "places.xml"
    works = tmp_path / "works.xml"
    manuscript = tmp_path / "manuscript.xml"
    report = tmp_path / "report.json"

    original_persons = """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><listPerson type="local"></listPerson></body></text></TEI>"""
    original_places = """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><listPlace type="local"></listPlace><listOrg type="local"></listOrg></body></text></TEI>"""
    original_works = """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><listBibl type="authors"></listBibl><listBibl type="anonymous"></listBibl></body></text></TEI>"""
    original_manuscript = """<TEI xml:id="manuscript_1" xmlns="http://www.tei-c.org/ns/1.0"><text><body><msDesc><msContents><msItem><persName ref="https://www.wikidata.org/entity/Q12345">John Example</persName></msItem></msContents></msDesc></body></text></TEI>"""
    persons.write_text(original_persons, encoding="utf-8")
    places.write_text(original_places, encoding="utf-8")
    works.write_text(original_works, encoding="utf-8")
    manuscript.write_text(original_manuscript, encoding="utf-8")

    args = SimpleNamespace(
        command="enrich",
        dry_run=True,
        keep_ref=False,
        inputs=[str(manuscript)],
        persons=persons,
        places=places,
        works=works,
        report=report,
        no_fetch=True,
        person_min_id=1,
        place_min_id=1,
        org_min_id=1,
        work_min_id=1,
    )

    assert module.run_enrich(args, client) == 0

    assert persons.read_text(encoding="utf-8") == original_persons
    assert places.read_text(encoding="utf-8") == original_places
    assert works.read_text(encoding="utf-8") == original_works
    assert manuscript.read_text(encoding="utf-8") == original_manuscript
    payload = module.json.loads(report.read_text(encoding="utf-8"))
    output = capsys.readouterr().out

    assert payload["apply"] is False
    assert payload["new_entries"][0]["key"] == "person_1"
    assert payload["changed_manuscript_files"] == 0
    assert (
        "Dry-run mode. No manuscript or authority files were modified."
        in output
    )


def test_run_reconcile_apply_adds_approved_wikidata_link(
    module, client, tmp_path: Path, capsys
) -> None:
    persons = tmp_path / "persons.xml"
    report = tmp_path / "report.json"

    persons.write_text(
        """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><listPerson type="local">
            <person xml:id="person_4803">
               <persName type="display">Carne, Sir Edward, 1496?–1561</persName>
            </person>
            </listPerson></body></text></TEI>""",
        encoding="utf-8",
    )
    report.write_text(
        module.json.dumps(
            {
                "entries": [
                    {
                        "entity_type": "person",
                        "key": "person_4803",
                        "candidates": [{"qid": "Q7526531", "approved": True}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    args = SimpleNamespace(
        command="reconcile",
        persons=persons,
        report=report,
        reconcile_limit=5,
        apply=True,
        no_fetch=True,
    )

    assert module.run_reconcile(args, client) == 0

    updated_persons = persons.read_text(encoding="utf-8")
    output = capsys.readouterr().out
    assert "https://www.wikidata.org/entity/Q7526531" in updated_persons
    assert "<title>Wikidata</title>" in updated_persons
    assert "Approved reconciliations found: 1" in output
    assert "Updated person entries: 1" in output


def test_approved_reconciliations_from_report_rejects_multiple_approved_candidates(
    module, tmp_path: Path
) -> None:
    report = tmp_path / "report.json"
    report.write_text(
        module.json.dumps(
            {
                "entries": [
                    {
                        "entity_type": "person",
                        "key": "person_4803",
                        "candidates": [
                            {"qid": "Q1", "approved": True},
                            {"qid": "Q2", "approved": True},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    import pytest

    with pytest.raises(
        ValueError, match="Multiple approved candidates found for person_4803"
    ):
        module.approved_reconciliations_from_report(report)


def test_regenerate_entry_requires_existing_or_explicit_wikidata_qid(
    module, client, tmp_path: Path
) -> None:
    persons = tmp_path / "persons.xml"
    places = tmp_path / "places.xml"
    works = tmp_path / "works.xml"
    persons.write_text(
        """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><listPerson type="local">
            <person xml:id="person_4803">
               <persName type="display">Old Label</persName>
            </person>
            </listPerson></body></text></TEI>""",
        encoding="utf-8",
    )
    places.write_text(
        """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><listPlace type="local"></listPlace><listOrg type="local"></listOrg></body></text></TEI>""",
        encoding="utf-8",
    )
    works.write_text(
        """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><listBibl type="anonymous"></listBibl></body></text></TEI>""",
        encoding="utf-8",
    )

    import pytest

    with pytest.raises(
        ValueError, match="Cannot regenerate person_4803 from Q999"
    ):
        module.regenerate_entry(
            "person_4803",
            "Q999",
            persons_path=persons,
            places_path=places,
            works_path=works,
            client=client,
            min_ids={"person": 1, "place": 1, "org": 1, "work": 1},
        )


def test_run_enrich_aborts_on_duplicate_authority_identifiers(
    module, client, tmp_path: Path
) -> None:
    persons = tmp_path / "persons.xml"
    places = tmp_path / "places.xml"
    works = tmp_path / "works.xml"
    manuscript = tmp_path / "manuscript.xml"
    report = tmp_path / "report.json"

    duplicate_link = "https://www.wikidata.org/entity/Q123"
    persons.write_text(
        f"""<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><listPerson type="local">
            <person xml:id="person_1"><persName type="display">One</persName><note type="links"><list type="links"><item><ref target="{duplicate_link}"><title>Wikidata</title></ref></item></list></note></person>
            <person xml:id="person_2"><persName type="display">Two</persName><note type="links"><list type="links"><item><ref target="{duplicate_link}"><title>Wikidata</title></ref></item></list></note></person>
            </listPerson></body></text></TEI>""",
        encoding="utf-8",
    )
    places.write_text(
        """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><listPlace type="local"></listPlace><listOrg type="local"></listOrg></body></text></TEI>""",
        encoding="utf-8",
    )
    works.write_text(
        """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><listBibl type="authors"></listBibl><listBibl type="anonymous"></listBibl></body></text></TEI>""",
        encoding="utf-8",
    )
    manuscript.write_text(
        """<TEI xml:id="manuscript_1" xmlns="http://www.tei-c.org/ns/1.0"><text><body><msDesc><msContents><msItem><persName ref="https://www.wikidata.org/entity/Q12345">John Example</persName></msItem></msContents></msDesc></body></text></TEI>""",
        encoding="utf-8",
    )

    args = SimpleNamespace(
        command="enrich",
        dry_run=False,
        keep_ref=False,
        inputs=[str(manuscript)],
        persons=persons,
        places=places,
        works=works,
        report=report,
        no_fetch=True,
        person_min_id=1,
        place_min_id=1,
        org_min_id=1,
        work_min_id=1,
    )

    import pytest

    with pytest.raises(
        ValueError,
        match="Duplicate external identifiers found in authority files",
    ):
        module.run_enrich(args, client)


def test_run_add_creates_place_entry_from_wikidata_ref(
    module, client, tmp_path: Path, capsys
) -> None:
    persons = tmp_path / "persons.xml"
    places = tmp_path / "places.xml"
    works = tmp_path / "works.xml"
    report = tmp_path / "report.json"

    persons.write_text(
        """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><listPerson type="local"></listPerson><listPerson type="VIAF"></listPerson></body></text></TEI>""",
        encoding="utf-8",
    )
    places.write_text(
        """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>
            <listPlace type="local"></listPlace>
            <listPlace type="TGN">
               <place xml:id="place_7008590" type="country">
                  <placeName type="index">Earlier</placeName>
               </place>
               <place xml:id="place_7008592" type="country">
                  <placeName type="index">Later</placeName>
               </place>
            </listPlace>
            <listPlace type="geonames"></listPlace>
            <listOrg type="local"></listOrg>
            <listOrg type="VIAF"></listOrg>
            </body></text></TEI>""",
        encoding="utf-8",
    )
    works.write_text(
        """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><listBibl type="authors"></listBibl><listBibl type="anonymous"></listBibl></body></text></TEI>""",
        encoding="utf-8",
    )

    client._entity_cache.update(
        {
            "Q145": {
                "labels": {"en": {"value": "United Kingdom"}},
                "claims": {
                    "P31": [
                        {"mainsnak": {"datavalue": {"value": {"id": "Q6256"}}}}
                    ],
                    "P1566": [
                        {"mainsnak": {"datavalue": {"value": "2635167"}}}
                    ],
                    "P1667": [
                        {"mainsnak": {"datavalue": {"value": "7008591"}}}
                    ],
                },
            }
        }
    )

    args = SimpleNamespace(
        persons=persons,
        places=places,
        works=works,
        no_fetch=False,
        dry_run=False,
        refs=["Q145"],
        entity_type=None,
        person_min_id=1,
        place_min_id=1,
        org_min_id=1,
        work_min_id=1,
        report=report,
    )

    assert module.run_add(args, client) == 0

    updated_places = places.read_text(encoding="utf-8")
    assert updated_places.index('xml:id="place_7008590"') < updated_places.index(
        'xml:id="place_7008591"'
    ) < updated_places.index('xml:id="place_7008592"')
    assert "United Kingdom" in updated_places

    output = capsys.readouterr().out
    assert "added place_7008591 <- Q145 (place)" in output
    assert report.exists()
