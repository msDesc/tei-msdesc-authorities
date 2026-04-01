from __future__ import annotations

from pathlib import Path

from lxml import etree
import pytest
from tei_msdesc_authorities.authorities import dimev as DIMEV_MODULE


@pytest.mark.parametrize(
    ("details_kwargs", "expected"),
    [
        (
            {
                "source_identifier": "Q1",
                "label": "Price, Gregory",
                "birth": "1535-08-06",
                "death": "1600-03-19",
            },
            "Price, Gregory, 1535–1600",
        ),
        (
            {
                "source_identifier": "Q2",
                "label": "Carne, Sir Edward",
                "display_subtype": "surnameFirst",
                "honorific_prefix": "Sir",
                "birth": "1496",
                "birth_uncertain": True,
                "death": "1561",
            },
            "Carne, Sir Edward, 1496?–1561",
        ),
    ],
)
def test_display_label_for_person(
    module, details_kwargs: dict[str, object], expected: str
) -> None:
    source_identifier = str(details_kwargs["source_identifier"])
    details_kwargs = {
        **{
            key: value
            for key, value in details_kwargs.items()
            if key != "source_identifier"
        },
        "source": module.SourceRef("wikidata", source_identifier, "Wikidata"),
    }
    details = module.EntityDetails(**details_kwargs)
    assert module.display_label_for_person(details) == expected


def test_build_person_details_reorders_honorific_surname_first_name(
    module, client
) -> None:
    client._entity_cache.update(
        {
            "QMAIN": {
                "labels": {"en": {"value": "Sir Edward Carne"}},
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
                    "P511": [
                        {"mainsnak": {"datavalue": {"value": {"id": "QHON"}}}}
                    ],
                    "P569": [
                        {
                            "mainsnak": {
                                "datavalue": {
                                    "value": {
                                        "time": "+1496-00-00T00:00:00Z",
                                        "precision": 9,
                                    }
                                }
                            },
                            "qualifiers": {
                                "P1480": [
                                    {
                                        "datavalue": {
                                            "value": {"id": "QUNCERTAIN"}
                                        }
                                    }
                                ]
                            },
                        }
                    ],
                    "P570": [
                        {
                            "mainsnak": {
                                "datavalue": {
                                    "value": {
                                        "time": "+1561-00-00T00:00:00Z",
                                        "precision": 9,
                                    }
                                }
                            }
                        }
                    ],
                },
            },
            "QGIVEN": {"labels": {"en": {"value": "Edward"}}},
            "QFAMILY": {"labels": {"en": {"value": "Carne"}}},
            "QHON": {"labels": {"en": {"value": "Sir"}}},
            "QUNCERTAIN": {"labels": {"en": {"value": "circa"}}},
        }
    )

    details = module.build_person_details("QMAIN", "Sir Edward Carne", client)

    assert details.label == "Carne, Sir Edward"
    assert details.birth_uncertain is True
    assert (
        module.display_label_for_person(details)
        == "Carne, Sir Edward, 1496?–1561"
    )


def test_build_person_snippet_sets_cert_for_approximate_dates(module) -> None:
    details = module.EntityDetails(
        source=module.SourceRef("wikidata", "Q2", "Wikidata"),
        label="Carne, Sir Edward",
        display_subtype="surnameFirst",
        birth="1496",
        birth_uncertain=True,
        death="1561",
    )

    snippet = module.build_person_snippet("person_4803", details)

    assert '<birth cert="medium" source="Wikidata" when="1496"/>' in snippet
    assert '<death source="Wikidata" when="1561"/>' in snippet
    assert "Carne, Sir Edward, 1496?–1561" in snippet


def test_read_person_authority_records_collects_variant_labels(
    module, tmp_path: Path
) -> None:
    authority = tmp_path / "persons.xml"
    authority.write_text(
        """<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <text>
    <body>
      <listPerson>
        <person xml:id="person_1">
          <persName type="display">Chaucer, Geoffrey, –1400</persName>
          <persName type="variant">Geoffrey Chaucer</persName>
          <persName type="variant">Geffrey Chaucer</persName>
        </person>
      </listPerson>
    </body>
  </text>
</TEI>""",
        encoding="utf-8",
    )

    records = module.read_person_authority_records(authority)

    assert records["person_1"].display_label == "Chaucer, Geoffrey, –1400"
    assert records["person_1"].variant_labels == (
        "Geoffrey Chaucer",
        "Geffrey Chaucer",
    )


def test_build_person_name_index_includes_unambiguous_variant_labels(
    module,
) -> None:
    records = {
        "person_1": module.PersonAuthorityRecord(
            key="person_1",
            display_label="Chaucer, Geoffrey, –1400",
            variant_labels=("Geffrey Chaucer",),
        ),
        "person_2": module.PersonAuthorityRecord(
            key="person_2",
            display_label="Gower, John, –1408",
        ),
    }

    index = module.build_person_name_index(records)

    assert index["geoffrey chaucer"] == "person_1"
    assert index["chaucer geoffrey"] == "person_1"
    assert index["geffrey chaucer"] == "person_1"


def test_build_place_details_rounds_coordinates_and_sets_country_type(
    module, client
) -> None:
    client._entity_cache.update(
        {
            "QPLACE": {
                "labels": {"en": {"value": "Kingdom of Sicily"}},
                "claims": {
                    "P31": [
                        {
                            "mainsnak": {
                                "datavalue": {"value": {"id": "Q3024240"}}
                            }
                        }
                    ],
                    "P625": [
                        {
                            "mainsnak": {
                                "datavalue": {
                                    "value": {
                                        "latitude": 38.591944444444444,
                                        "longitude": 16.07888888888889,
                                        "precision": 0.0002777777777777778,
                                    }
                                }
                            }
                        }
                    ],
                },
            }
        }
    )

    details = module.build_place_details("QPLACE", "Kingdom of Sicily", client)

    assert details.place_type == "country"
    assert details.coordinates is not None
    assert details.coordinates.latitude == "38.5919"
    assert details.coordinates.longitude == "16.0789"


def test_build_place_snippet_emits_type_and_rounded_geo(module) -> None:
    details = module.EntityDetails(
        source=module.SourceRef("wikidata", "QPLACE", "Wikidata"),
        label="Kingdom of Sicily",
        place_type="country",
        coordinates=module.CoordinatePoint(
            latitude="38.5919", longitude="16.0789"
        ),
    )

    snippet = module.build_place_snippet("place_7594681", details)

    assert '<place type="country" xml:id="place_7594681">' in snippet
    assert "<geo>38.5919,16.0789</geo>" in snippet


def test_route_entity_prefers_tgn_over_geonames_for_places(module) -> None:
    details = module.EntityDetails(
        source=module.SourceRef("wikidata", "Q145", "Wikidata"),
        label="United Kingdom",
        external_identifiers=(
            module.ExternalIdentifier("geonames", "2635167"),
            module.ExternalIdentifier("tgn", "7008591"),
        ),
    )

    route = module.route_entity(details, module.EntityType.PLACE)

    assert route.list_tag == "listPlace"
    assert route.list_type == "TGN"


def test_assign_key_for_details_prefers_tgn_over_geonames_for_places(
    module,
) -> None:
    details = module.EntityDetails(
        source=module.SourceRef("wikidata", "Q145", "Wikidata"),
        label="United Kingdom",
        external_identifiers=(
            module.ExternalIdentifier("geonames", "2635167"),
            module.ExternalIdentifier("tgn", "7008591"),
        ),
    )

    key = module.assign_key_for_details(
        details,
        module.EntityType.PLACE,
        {"person": set(), "place": set(), "org": set(), "work": set()},
        {"person": 1, "place": 1, "org": 1, "work": 1},
    )

    assert key == "place_7008591"


def test_parse_add_ref_spec_accepts_dimev_url(module) -> None:
    target = module.parse_add_ref_spec(
        "https://www.dimev.net/record.php?recID=2613"
    )

    assert target.entity_type == module.EntityType.WORK
    assert target.source == "dimev"
    assert target.identifier == "2613"
    assert target.display_id == "DIMEV:2613"


def test_parse_add_ref_spec_accepts_legacy_dwm27_dimev_url(module) -> None:
    target = module.parse_add_ref_spec(
        "https://dwm27.net/dimev/record.php?recID=2983"
    )

    assert target.entity_type == module.EntityType.WORK
    assert target.source == "dimev"
    assert target.identifier == "2983"


def test_parse_add_ref_spec_rejects_non_work_dimev_ref(module) -> None:
    with pytest.raises(
        ValueError, match="DIMEV refs can only be used for work entries"
    ):
        module.parse_add_ref_spec("place:dimev:2613")


def test_build_dimev_work_details_uses_record_metadata(module) -> None:
    client = module.DimevClient(no_fetch=False)
    client._record_cache["2613"] = module.DimevRecord(
        record_id="2613",
        title="In the name of the blessed Trinity",
        title_variants=(),
        authors=(),
        first_lines=(
            "In the name of the blessid trinyte The fader þe sone and þe holi goost",
        ),
        last_lines=(),
        subjects=("prayers", "domestic life"),
        imev_id="1557",
        nimev_id="1557",
    )

    details = module.build_dimev_work_details("2613", client)

    assert details.source_id == "DIMEV:2613"
    assert details.label == "In the name of the blessed Trinity"
    assert details.source_name == "DIMEV"
    assert details.source_ref == "https://www.dimev.net/record.php?recID=2613"
    assert details.label_lang == "enm"
    assert details.main_lang == "enm"
    assert details.main_lang_label == "Middle English"
    assert details.incipit.startswith("In the name of the blessid trinyte")
    assert details.incipit_lang == "enm"
    assert details.subjects == ("prayers", "domestic life")
    assert [(link.title, link.target) for link in details.links] == [
        (
            "Digital Index of Middle English Verse",
            "https://www.dimev.net/record.php?recID=2613",
        ),
        (
            "Index of Middle English Verse",
            "https://www.dimev.net/Results.php?imev=1557",
        ),
        (
            "New Index of Middle English Verse",
            "https://www.dimev.net/Results.php?nimev=1557",
        ),
    ]


def test_build_dimev_work_details_prefers_title_and_matches_author(module) -> None:
    client = module.DimevClient(no_fetch=False)
    client._record_cache["2983"] = module.DimevRecord(
        record_id="2983",
        title="A hymn to St. Katharine of Sinai",
        title_variants=("Katherine the courteous of all that I know",),
        authors=(
            module.DimevAuthor(first="Richard", last="Spaldyng"),
        ),
        first_lines=("Kateryne þe curteys of all þat I know",),
        last_lines=(),
        subjects=("hymns", "saints"),
        imev_id="1813",
        nimev_id="1813",
    )

    details = module.build_dimev_work_details(
        "2983",
        client,
        lambda author: ("person_42", "Spaldyng, Richard", None),
    )

    assert details.label == "A hymn to St. Katharine of Sinai"
    assert [(variant.value, variant.lang) for variant in details.variants] == [
        ("Katherine the courteous of all that I know", None)
    ]
    assert [(author.key, author.label, author.source) for author in details.authors] == [
        ("person_42", "Spaldyng, Richard", None)
    ]


def test_parse_dimev_record_reads_repository_xml(module) -> None:
    records = etree.fromstring(
        """<records>
        <record xml:id="record-2613">
            <name>In the name of the blessed Trinity</name>
            <repertories>
                <repertory key="Brown1943">1557</repertory>
                <repertory key="NIMEV">1557</repertory>
            </repertories>
            <witnesses>
                <witness xml:id="wit-2613-1">
                    <firstLines>In the name of þe blessid trinyte<lb/>The fader þe sone</firstLines>
                </witness>
            </witnesses>
        </record>
    </records>"""
    )

    record = module.parse_dimev_record(records, "2613")

    assert record is not None
    assert record.record_id == "2613"
    assert record.title == "In the name of the blessed Trinity"
    assert record.imev_id == "1557"
    assert record.nimev_id == "1557"
    assert record.first_lines == ("In the name of þe blessid trinyte\nThe fader þe sone",)


def test_parse_dimev_record_reads_titles_and_authors(module) -> None:
    records = etree.fromstring(
        """<records>
        <record xml:id="record-2983">
            <name>Katherine the courteous of all that I know</name>
            <titles>
                <title>A hymn to St. Katharine of Sinai</title>
            </titles>
            <authors>
                <author>
                    <last>Spaldyng</last>
                    <first>Richard</first>
                </author>
            </authors>
        </record>
    </records>"""
    )

    record = module.parse_dimev_record(records, "2983")

    assert record is not None
    assert record.title == "A hymn to St. Katharine of Sinai"
    assert record.title_variants == ("Katherine the courteous of all that I know",)
    assert [author.display_name for author in record.authors] == [
        "Spaldyng, Richard"
    ]


def test_parse_dimev_record_collects_all_first_and_last_lines_and_subjects(module) -> None:
    records = etree.fromstring(
        """<records>
        <record xml:id="record-1">
            <name>Title</name>
            <subjects>
                <subject>agriculture</subject>
                <subject>household</subject>
            </subjects>
            <witnesses>
                <witness xml:id="wit-1-1">
                    <firstLines>Alpha<lb/>Beta…</firstLines>
                    <lastLines>…Omega<lb/>Zeta</lastLines>
                </witness>
                <witness xml:id="wit-1-2">
                    <firstLines>Gamma</firstLines>
                    <lastLines>Delta...</lastLines>
                </witness>
            </witnesses>
        </record>
    </records>"""
    )

    record = module.parse_dimev_record(records, "1")

    assert record is not None
    assert record.first_lines == ("Alpha\nBeta", "Gamma")
    assert record.last_lines == ("Omega\nZeta", "Delta")
    assert record.subjects == ("agriculture", "household")


def test_dimev_client_reuses_on_disk_cache_between_runs(tmp_path: Path) -> None:
    payload = b"""<records>
    <record xml:id="record-1">
        <name>Cached title</name>
    </record>
</records>"""

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def read(self) -> bytes:
            return payload

    original_urlopen = DIMEV_MODULE.urllib.request.urlopen
    DIMEV_MODULE.urllib.request.urlopen = lambda *_args, **_kwargs: FakeResponse()
    try:
        first_client = DIMEV_MODULE.DimevClient(
            no_fetch=False,
            cache_dir=tmp_path,
        )
        first_record = first_client.get_record("1")
    finally:
        DIMEV_MODULE.urllib.request.urlopen = original_urlopen

    assert first_record is not None
    assert first_record.title == "Cached title"
    assert (tmp_path / "dimev-records.xml").exists()

    def fail_urlopen(*_args, **_kwargs):
        raise AssertionError("network should not be used when cached XML exists")

    DIMEV_MODULE.urllib.request.urlopen = fail_urlopen
    try:
        second_client = DIMEV_MODULE.DimevClient(
            no_fetch=True,
            cache_dir=tmp_path,
        )
        second_record = second_client.get_record("1")
    finally:
        DIMEV_MODULE.urllib.request.urlopen = original_urlopen

    assert second_record is not None
    assert second_record.title == "Cached title"


def test_build_work_snippet_uses_dimev_source_name(module) -> None:
    details = module.EntityDetails(
        source=module.SourceRef("dimev", "2613", "DIMEV"),
        label="In the name of the blessed Trinity",
        source_ref="https://www.dimev.net/record.php?recID=2613",
        links=(
            module.LinkItem(
                title="Digital Index of Middle English Verse",
                target="https://www.dimev.net/record.php?recID=2613",
            ),
        ),
        main_lang="enm",
        main_lang_label="Middle English",
        incipit="In the name of the blessid trinyte",
        incipit_lang="enm",
        extra_incipits=("The fader þe sone and þe holi goost",),
        explicits=("Where on þow suffred þi passyon pyne",),
        subjects=("prayers", "domestic life"),
    )

    snippet = module.build_work_snippet("work_1", details)

    assert (
        '<title source="DIMEV" type="primary">In the name of the blessed Trinity</title>'
        in snippet
    )
    assert 'source="DIMEV" type="uniform"' in snippet
    assert '<title>Digital Index of Middle English Verse</title>' in snippet
    assert (
        '<incipit source="DIMEV" xml:lang="enm">In the name of the blessid trinyte</incipit>'
        in snippet
    )
    assert (
        '<incipit source="DIMEV" xml:lang="enm">The fader þe sone and þe holi goost</incipit>'
        in snippet
    )
    assert (
        '<explicit source="DIMEV" xml:lang="enm">Where on þow suffred þi passyon pyne</explicit>'
        in snippet
    )
    assert '<term source="DIMEV">prayers</term>' in snippet
    assert '<term source="DIMEV">domestic life</term>' in snippet


def test_format_text_with_lbs_preserves_breaks(module) -> None:
    assert (
        module.format_text_with_lbs("Alpha\nBeta & Gamma")
        == "Alpha<lb/>Beta &amp; Gamma"
    )


def test_external_id_links_use_trusted_property_classes_only(
    module, client
) -> None:
    client._entity_cache.update(
        {
            "PTRUST": {
                "labels": {"en": {"value": "Trusted source ID"}},
                "claims": {
                    "P31": [
                        {
                            "mainsnak": {
                                "datavalue": {"value": {"id": "Q55452870"}}
                            }
                        }
                    ],
                    "P1630": [
                        {
                            "mainsnak": {
                                "datavalue": {
                                    "value": "https://example.org/trusted/$1"
                                }
                            }
                        }
                    ],
                },
            },
            "PUNTRUST": {
                "labels": {"en": {"value": "Untrusted source ID"}},
                "claims": {
                    "P31": [
                        {
                            "mainsnak": {
                                "datavalue": {"value": {"id": "Q62589316"}}
                            }
                        }
                    ],
                    "P1630": [
                        {
                            "mainsnak": {
                                "datavalue": {
                                    "value": "https://example.org/untrusted/$1"
                                }
                            }
                        }
                    ],
                },
            },
            "P9015": {
                "labels": {"en": {"value": "MMOL person ID"}},
                "claims": {
                    "P31": [
                        {
                            "mainsnak": {
                                "datavalue": {"value": {"id": "Q96192295"}}
                            }
                        }
                    ],
                    "P1630": [
                        {
                            "mainsnak": {
                                "datavalue": {
                                    "value": "https://medieval.bodleian.ox.ac.uk/catalog/person_$1"
                                }
                            }
                        }
                    ],
                },
            },
        }
    )
    entity = {
        "claims": {
            "PTRUST": [
                {
                    "mainsnak": {
                        "datatype": "external-id",
                        "datavalue": {"value": "123"},
                    }
                }
            ],
            "PUNTRUST": [
                {
                    "mainsnak": {
                        "datatype": "external-id",
                        "datavalue": {"value": "456"},
                    }
                }
            ],
            "P9015": [
                {
                    "mainsnak": {
                        "datatype": "external-id",
                        "datavalue": {"value": "4803"},
                    }
                }
            ],
        }
    }

    links = module.external_id_links(entity, client)

    assert [link.target for link in links] == [
        "https://example.org/trusted/123"
    ]


def test_external_id_links_accepts_newly_trusted_property_classes(
    module, client
) -> None:
    client._entity_cache.update(
        {
            "PCLASSA": {
                "labels": {"en": {"value": "Trusted class A ID"}},
                "claims": {
                    "P31": [
                        {
                            "mainsnak": {
                                "datavalue": {"value": {"id": "Q29547399"}}
                            }
                        }
                    ],
                    "P1630": [
                        {
                            "mainsnak": {
                                "datavalue": {
                                    "value": "https://example.org/class-a/$1"
                                }
                            }
                        }
                    ],
                },
            },
            "PCLASSB": {
                "labels": {"en": {"value": "Trusted class B ID"}},
                "claims": {
                    "P31": [
                        {
                            "mainsnak": {
                                "datavalue": {"value": {"id": "Q29546563"}}
                            }
                        }
                    ],
                    "P1630": [
                        {
                            "mainsnak": {
                                "datavalue": {
                                    "value": "https://example.org/class-b/$1"
                                }
                            }
                        }
                    ],
                },
            },
        }
    )
    entity = {
        "claims": {
            "PCLASSA": [
                {
                    "mainsnak": {
                        "datatype": "external-id",
                        "datavalue": {"value": "111"},
                    }
                }
            ],
            "PCLASSB": [
                {
                    "mainsnak": {
                        "datatype": "external-id",
                        "datavalue": {"value": "222"},
                    }
                }
            ],
        }
    }

    links = module.external_id_links(entity, client)

    assert [link.target for link in links] == [
        "https://example.org/class-a/111",
        "https://example.org/class-b/222",
    ]


def test_build_org_details_avoids_duplicate_curated_identifier_links(
    module, client
) -> None:
    client._entity_cache.update(
        {
            "QORG": {
                "labels": {"en": {"value": "Example House"}},
                "claims": {
                    "P213": [
                        {
                            "mainsnak": {
                                "datatype": "external-id",
                                "datavalue": {"value": "0000000123456789"},
                            }
                        }
                    ],
                    "P244": [
                        {
                            "mainsnak": {
                                "datatype": "external-id",
                                "datavalue": {"value": "n12345678"},
                            }
                        }
                    ],
                },
            },
            "P213": {
                "labels": {"en": {"value": "ISNI ID"}},
                "claims": {
                    "P1630": [
                        {
                            "mainsnak": {
                                "datavalue": {
                                    "value": "https://isni.org/isni/$1"
                                }
                            }
                        }
                    ]
                },
            },
            "P244": {
                "labels": {"en": {"value": "Library of Congress authority ID"}},
                "claims": {
                    "P1630": [
                        {
                            "mainsnak": {
                                "datavalue": {
                                    "value": "https://id.loc.gov/authorities/names/$1"
                                }
                            }
                        }
                    ]
                },
            },
        }
    )

    details = module.build_org_details("QORG", "Example House", client)

    assert [link.title for link in details.links].count("ISNI") == 1
    assert [link.title for link in details.links].count(
        "Library of Congress"
    ) == 1
    assert [link.target for link in details.links if link.title == "ISNI"] == [
        "http://www.isni.org/isni/0000000123456789"
    ]
    assert [
        link.target
        for link in details.links
        if link.title == "Library of Congress"
    ] == ["http://id.loc.gov/authorities/names/n12345678"]


def test_build_link_items_use_expanded_national_library_titles(module) -> None:
    entity = {
        "claims": {
            "P244": [{"mainsnak": {"datavalue": {"value": "n12345678"}}}],
            "P227": [{"mainsnak": {"datavalue": {"value": "118540238"}}}],
            "P268": [{"mainsnak": {"datavalue": {"value": "12345678x"}}}],
        }
    }

    links = module.build_link_items(entity, "Q1", module.PERSON_ID_LINKS)

    assert any(link.title == "Library of Congress" for link in links)
    assert any(link.title == "Deutsche Nationalbibliothek" for link in links)
    assert any(
        link.title == "Bibliothèque nationale de France" for link in links
    )


def test_dedupe_links_sorts_titles_accent_insensitively(module) -> None:
    links = module.dedupe_links(
        [
            module.LinkItem(
                title="Österreichisches Musiklexikon",
                target="https://example.org/o",
            ),
            module.LinkItem(title="ARLIMA", target="https://example.org/a"),
            module.LinkItem(
                title="The Medieval Review",
                target="https://example.org/m",
            ),
        ]
    )

    assert [link.title for link in links] == [
        "ARLIMA",
        "The Medieval Review",
        "Österreichisches Musiklexikon",
    ]


@pytest.mark.parametrize(
    ("floruit", "expected"),
    [
        (
            lambda module: module.FloruitRange(
                from_value="1220",
                to_value="1249",
                from_precision=8,
                to_precision=8,
            ),
            '<floruit cert="low" from="1220" to="1249"/>',
        ),
        (
            lambda module: module.FloruitRange(
                from_value="1201",
                to_value="1300",
                from_precision=7,
                to_precision=7,
            ),
            '<floruit cert="low" from="1201" to="1300"/>',
        ),
    ],
)
def test_build_person_snippet_sets_low_cert_for_non_year_floruit(
    module, floruit, expected: str
) -> None:
    details = module.EntityDetails(
        source=module.SourceRef("wikidata", "Q3", "Wikidata"),
        label="Example Person",
        floruit=floruit(module),
    )

    snippet = module.build_person_snippet("person_9999", details)

    assert expected in snippet


def test_build_person_details_collects_keyed_org_and_place_relations(
    module, client
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
                    "P937": [
                        {
                            "mainsnak": {
                                "datavalue": {"value": {"id": "QWORKPLACE"}}
                            }
                        }
                    ],
                    "P69": [
                        {"mainsnak": {"datavalue": {"value": {"id": "QUNIV"}}}}
                    ],
                    "P27": [
                        {
                            "mainsnak": {
                                "datavalue": {"value": {"id": "QCOUNTRY"}}
                            }
                        }
                    ],
                    "P551": [
                        {"mainsnak": {"datavalue": {"value": {"id": "QCITY"}}}}
                    ],
                    "P106": [
                        {"mainsnak": {"datavalue": {"value": {"id": "QOCC"}}}}
                    ],
                },
            },
            "QGIVEN": {"labels": {"en": {"value": "John"}}},
            "QFAMILY": {"labels": {"en": {"value": "Example"}}},
            "QORDER": {"labels": {"en": {"value": "Order of Preachers"}}},
            "QWORKPLACE": {"labels": {"en": {"value": "Cirencester Abbey"}}},
            "QUNIV": {"labels": {"en": {"value": "University of Paris"}}},
            "QCOUNTRY": {"labels": {"en": {"value": "France"}}},
            "QCITY": {"labels": {"en": {"value": "Paris"}}},
            "QOCC": {"labels": {"en": {"value": "theologian"}}},
        }
    )

    def ensure_related(
        entity_type: str, qid: str, fallback: str
    ) -> tuple[str, str]:
        mapping = {
            ("org", "QORDER"): ("org_100", "Order of Preachers"),
            ("org", "QWORKPLACE"): ("org_102", "Cirencester Abbey"),
            ("org", "QUNIV"): ("org_101", "University of Paris"),
            ("place", "QCOUNTRY"): ("place_200", "France"),
            ("place", "QCITY"): ("place_201", "Paris"),
        }
        return mapping[(entity_type, qid)]

    details = module.build_person_details(
        "QPERSON", "John Example", client, ensure_related
    )

    assert [
        (item.key, item.label, item.relation_type)
        for item in details.affiliations
    ] == [
        ("org_100", "Order of Preachers", "religiousOrder"),
        ("org_102", "Cirencester Abbey", "workPlace"),
    ]
    assert [(item.key, item.label) for item in details.educations] == [
        ("org_101", "University of Paris")
    ]
    assert [(item.key, item.label) for item in details.nationalities] == [
        ("place_200", "France")
    ]
    assert [(item.key, item.label) for item in details.residences] == [
        ("place_201", "Paris")
    ]
    assert [item.value for item in details.occupations] == ["theologian"]


def test_build_person_snippet_emits_keyed_org_and_place_relations(
    module,
) -> None:
    details = module.EntityDetails(
        source=module.SourceRef("wikidata", "QPERSON", "Wikidata"),
        label="Example, John",
        affiliations=(
            module.LinkedAuthorityRef(
                key="org_100",
                label="Order of Preachers",
                relation_type="religiousOrder",
            ),
            module.LinkedAuthorityRef(
                key="org_102",
                label="Cirencester Abbey",
                relation_type="workPlace",
            ),
        ),
        educations=(
            module.LinkedAuthorityRef(
                key="org_101", label="University of Paris"
            ),
        ),
        nationalities=(
            module.LinkedAuthorityRef(key="place_200", label="France"),
        ),
        residences=(module.LinkedAuthorityRef(key="place_201", label="Paris"),),
        occupations=(module.NameVariant("theologian", "en"),),
    )

    snippet = module.build_person_snippet("person_9998", details)

    assert (
        '<affiliation type="religiousOrder"><orgName key="org_100" source="Wikidata">Order of Preachers</orgName></affiliation>'
        in snippet
    )
    assert (
        '<affiliation type="workPlace"><orgName key="org_102" source="Wikidata">Cirencester Abbey</orgName></affiliation>'
        in snippet
    )
    assert (
        '<education><orgName key="org_101" source="Wikidata">University of Paris</orgName></education>'
        in snippet
    )
    assert (
        '<nationality key="place_200" source="Wikidata">France</nationality>'
        in snippet
    )
    assert (
        '<residence><placeName key="place_201" source="Wikidata">Paris</placeName></residence>'
        in snippet
    )
    assert (
        '<occupation source="Wikidata" xml:lang="en">theologian</occupation>'
        in snippet
    )


@pytest.mark.parametrize("qid", ["Q179876", "Q330362"])
def test_build_person_details_uses_local_equivalent_place_key(
    module, client, qid: str
) -> None:
    client._entity_cache.update(
        {
            "QPERSON": {
                "labels": {"en": {"value": "Edward Carne"}},
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
                    "P27": [
                        {"mainsnak": {"datavalue": {"value": {"id": qid}}}}
                    ],
                },
            },
            "QGIVEN": {"labels": {"en": {"value": "Edward"}}},
            "QFAMILY": {"labels": {"en": {"value": "Carne"}}},
            qid: {"labels": {"en": {"value": "England variant"}}},
        }
    )

    def ensure_related(
        entity_type: str, related_qid: str, fallback: str
    ) -> tuple[str, str]:
        if entity_type == "place" and related_qid == qid:
            return "place_7002445", "England"
        raise AssertionError(
            f"Unexpected related lookup: {(entity_type, related_qid, fallback)}"
        )

    details = module.build_person_details(
        "QPERSON", "Edward Carne", client, ensure_related
    )

    assert [(item.key, item.label) for item in details.nationalities] == [
        ("place_7002445", "England")
    ]
