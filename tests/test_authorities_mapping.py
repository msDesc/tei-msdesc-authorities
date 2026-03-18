from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    ("details_kwargs", "expected"),
    [
        (
            {
                "qid": "Q1",
                "label": "Price, Gregory",
                "birth": "1535-08-06",
                "death": "1600-03-19",
            },
            "Price, Gregory, 1535–1600",
        ),
        (
            {
                "qid": "Q2",
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
        qid="Q2",
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
        qid="QPLACE",
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
        qid="Q145",
        label="United Kingdom",
        external_ids=module.ExternalAuthorityIds(
            geonames="2635167",
            tgn="7008591",
        ),
    )

    route = module.route_entity(details, module.EntityType.PLACE)

    assert route.list_tag == "listPlace"
    assert route.list_type == "TGN"


def test_assign_key_for_details_prefers_tgn_over_geonames_for_places(
    module,
) -> None:
    details = module.EntityDetails(
        qid="Q145",
        label="United Kingdom",
        external_ids=module.ExternalAuthorityIds(
            geonames="2635167",
            tgn="7008591",
        ),
    )

    key = module.assign_key_for_details(
        details,
        module.EntityType.PLACE,
        {"person": set(), "place": set(), "org": set(), "work": set()},
        {"person": 1, "place": 1, "org": 1, "work": 1},
    )

    assert key == "place_7008591"


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
        qid="Q3",
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
        qid="QPERSON",
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
