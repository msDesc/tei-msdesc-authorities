from __future__ import annotations

import pytest

from tei_msdesc_authorities.authorities import cli as CLI_MODULE
from tei_msdesc_authorities.authorities import core as CORE_MODULE
from tei_msdesc_authorities.authorities.wikidata import WikidataClient


@pytest.fixture(scope="session")
def module():
    return CORE_MODULE


@pytest.fixture
def cli_module():
    return CLI_MODULE


@pytest.fixture
def core_module():
    return CORE_MODULE


@pytest.fixture
def client():
    return WikidataClient(no_fetch=True)
