# tei-msdesc-authorities

`tei-msdesc-authorities` is a command-line tool for maintaining TEI authority files alongside `msDesc` manuscript catalogues.

It is designed to let a cataloguer write a manuscript description using an external identifier in `@ref`, and then allow the authority-management work to be handled afterwards by a scripted workflow.

This tool is intended for projects such as Medieval Manuscripts in Oxford Libraries and Medieval Libraries of Great Britain, whose manuscript records contain references to people, places, organizations, and works that need to be grounded in shared local TEI authority files.

The current implementation supports:

- creating new authority entries from unresolved manuscript references
- enriching authority entries from Wikidata
- reconciling existing local people against likely Wikidata matches
- regenerating existing entries from their linked Wikidata record
- auditing authority files for duplicate `xml:id`, Wikidata, and VIAF values

## Overview

In a typical `msDesc` project, manuscript files contain elements such as:

- `<persName ref="https://www.wikidata.org/entity/Q123">`
- `<placeName ref="https://www.wikidata.org/entity/Q456">`
- `<orgName ref="https://www.wikidata.org/entity/Q789">`
- `<title ref="https://www.wikidata.org/entity/Q101112">`

Those external references need to become stable local authority keys such as:

- `person_4816`
- `place_7594681`
- `org_124074257`
- `work_6856`

and the corresponding records need to be inserted into the appropriate TEI authority files:

- `persons.xml`
- `places.xml`
- `works.xml`

`tei-msdesc-authorities` automates that workflow while preserving project-specific conventions such as:

- routing entries into typed authority lists such as `local`, `VIAF`, `TGN`, `geonames`, `authors`, and `anonymous`
- keeping inserted entries in numeric order within their target list
- generating TEI snippets with project-specific element structure and formatting
- reusing existing linked authorities where possible instead of creating duplicates

The intended pattern is simple: cataloguers can work with external `@ref` values during description, and a later automated or semi-automated pass turns them into normalized local authority references.

## Worked Example

Suppose a manuscript description contains an unresolved author reference:

```xml
<msItem>
   <author ref="https://www.wikidata.org/entity/Q117352696">Andrew Cook</author>
   <title>Example Text</title>
</msItem>
```

Running:

```bash
uv run authorities enrich collections/Example/Example_MS.xml
```

causes the tool to:

1. detect that the manuscript refers to a Wikidata entity without a local TEI
   authority `@key`
2. create or reuse a corresponding authority record in `persons.xml`
3. assign a local key such as `person_4815`
4. update the manuscript file to use that local authority key

The manuscript entry can then become:

```xml
<msItem>
   <author key="person_4815" ref="https://www.wikidata.org/entity/Q117352696">Andrew Cook</author>
   <title>Example Text</title>
</msItem>
```

and the corresponding authority entry might be created or regenerated as:

```xml
<person xml:id="person_4815">
   <persName source="Wikidata" subtype="surnameFirst" type="display">Cook, Andrew, –1633</persName>
   <persName source="Wikidata" type="variant">Andrew Cooke</persName>
   <death source="Wikidata" when="1633"/>
   <note type="links">
      <list type="links">
         <item>
            <ref target="https://www.wikidata.org/entity/Q117352696">
               <title>Wikidata</title>
            </ref>
         </item>
      </list>
   </note>
</person>
```

The exact generated content depends on the available source data and on whether the project already contains a matching local authority record.

The key workflow advantage is that manuscript cataloguing no longer has to be blocked on manual authority maintenance.

## External Source Support

The current implementation uses Wikidata as its enrichment and reconciliation source. Direct work creation from DIMEV repository data is also supported by `authorities add`.

## Requirements

- Python 3.14+
- [uv](https://docs.astral.sh/uv/)

## Installation

For development in this repository:

```bash
uv sync --dev
```

This installs the package, its console scripts, and the test dependencies.

## Command-Line Interface

The package installs two console commands:

- `authorities`
- `authority-identifiers`

## API Surface

This package is primarily intended to be used through its console scripts rather
than as a general-purpose Python library.

Its stable public interface is therefore:

- `authorities`
  - add authority entries directly from Wikidata IDs or URLs
  - enrich manuscript files and authority files
  - reconcile existing person authorities against Wikidata
  - regenerate existing authority entries
- `authority-identifiers`
  - check authority files for duplicate local and external identifiers

The internal Python modules are organized for maintainability, but the command
line is the main supported interface for downstream repositories.

### `authorities`

`authorities` is the main workflow command. It provides three subcommands:

- `add`
- `enrich`
- `reconcile`
- `regenerate`

#### `authorities add`

Add one or more authority entries directly from supported external source IDs or URLs, without
requiring a manuscript file to contain the corresponding `@ref` first.

Examples:

```bash
uv run authorities add Q145
uv run authorities add https://www.wikidata.org/entity/Q145
uv run authorities add place:Q145
uv run authorities add --as place Q145 Q21
uv run authorities add https://www.dimev.net/record.php?recID=2613
uv run authorities add dimev:2613
```

If the entity type is obvious, the command will infer it. Where there is no TEI
context and the type would otherwise be ambiguous, use either:

- `--as person|place|org|work`
- DIMEV refs are work-only and may be given either as full DIMEV record URLs or as `dimev:RECORD_ID`
- a typed spec such as `place:Q145`

Useful options:

- `--dry-run`: preview additions without writing authority files
- `--report`: write a JSON report of planned or applied additions
- `--person-min-id`, `--place-min-id`, `--org-min-id`, `--work-min-id`: control
  the minimum local numeric identifiers to allocate
  for newly created local keys

#### `authorities enrich`

Scan manuscript XML files for unresolved `@ref` values, create any missing authority entries, and write local `@key` values back to the manuscript files.

Example:

```bash
uv run authorities enrich collections/Jesus_College/Jesus_College_MS_94.xml
```

Useful options:

- `--dry-run`: preview changes without writing
- `--report`: write a JSON report of proposed or applied changes
- `--keep-ref`: preserve existing `@ref` values when adding `@key`
- `--person-min-id`, `--place-min-id`, `--org-min-id`, `--work-min-id`: control the minimum local numeric identifiers to allocate
- `--persons`, `--places`, `--works`: point to non-default authority files

If no input files are supplied, the command scans `collections/**/*.xml`.

#### `authorities reconcile`

Generate a report of likely Wikidata matches for existing local person authorities that do not already have a Wikidata link.

Example:

```bash
uv run authorities reconcile
```

This writes a JSON report, by default to:

```text
processing/authority_enrichment_report.json
```

The report includes suggested candidates and a place to mark approved matches.

To apply approved matches from that report:

```bash
uv run authorities reconcile --apply --report processing/authority_enrichment_report.json
```

Useful options:

- `--reconcile-limit`: maximum number of candidates to retain per entry
- `--report`: choose the JSON report path

#### `authorities regenerate`

Regenerate one or more existing authority entries from their Wikidata data.

Examples:

```bash
uv run authorities regenerate person_4803
uv run authorities regenerate person_4815=Q117352696
uv run authorities regenerate person_4816 person_4817
```

Forms accepted:

- `person_4803`
  - use the existing Wikidata link already recorded on that entry
- `person_4815=Q117352696`
  - regenerate from an explicit Wikidata QID
- `person_4815=https://www.wikidata.org/entity/Q117352696`
  - regenerate from an explicit Wikidata entity URL

If regenerating one entry requires new linked place or organization authorities to be created, those related creations are reported in the terminal output.

### `authority-identifiers`

Audit authority files for duplicate:

- `xml:id`
- Wikidata IDs
- VIAF IDs

Example:

```bash
uv run authority-identifiers
```

You can also point it at explicit authority files:

```bash
uv run authority-identifiers persons.xml places.xml works.xml
```

The output uses `path:line` formatting so the reported locations are clickable in editors such as VS Code.

## Expected Authority Layout

The tool assumes a project layout with separate authority files for people, places/organizations, and works.

By default it expects:

- `persons.xml`
- `places.xml`
- `works.xml`

It also assumes that these files contain typed TEI lists used to route new records. For example:

- `<listPerson type="local">`
- `<listPerson type="VIAF">`
- `<listPlace type="local">`
- `<listPlace type="TGN">`
- `<listPlace type="geonames">`
- `<listOrg type="local">`
- `<listOrg type="VIAF">`
- `<listBibl type="authors">`
- `<listBibl type="anonymous">`

New entries are inserted into the matching list and kept in numeric order within that list.

## Authority Routing Rules

The current routing rules reflect the conventions used by Bodleian authority files.

### People

- person with a VIAF identifier:
  - key format: `person_VIAFID`
  - inserted into `<listPerson type="VIAF">`
- person without a VIAF identifier:
  - key format: `person_NUMBER`
  - inserted into `<listPerson type="local">`

### Places

- place with a GeoNames identifier:
  - key format: `place_GEONAMESID`
  - inserted into `<listPlace type="geonames">`
- place with a Getty TGN identifier:
  - key format: `place_TGNID`
  - inserted into `<listPlace type="TGN">`
- place without those identifiers:
  - key format: `place_NUMBER`
  - inserted into `<listPlace type="local">`

### Organizations

- organization with a VIAF identifier:
  - key format: `org_VIAFID`
  - inserted into `<listOrg type="VIAF">`
- organization without a VIAF identifier:
  - key format: `org_NUMBER`
  - inserted into `<listOrg type="local">`

### Works

- work with an attribution:
  - key format: `work_NUMBER`
  - inserted into `<listBibl type="authors">`
- anonymous work:
  - key format: `work_NUMBER`
  - inserted into `<listBibl type="anonymous">`

For locally allocated numeric keys, the tool uses the smallest available number at or above the configured minimum for that entity type, while still preserving global uniqueness within the relevant authority file.

## Reports and Safety

The tool is deliberately conservative in a few places:

- reconciliation suggestions are report-first, not silently applied
- regeneration fails if live Wikidata data cannot be fetched
- duplicate identifiers in authority files are treated as errors
- linked local authorities are reused where possible to avoid duplication

This is intended to support editorial review rather than hide important authority management decisions.

## Development

Run the test suite with:

```bash
uv run pytest
```

Build distribution artifacts with:

```bash
uv build
```

The project uses:

- `src` layout
- `argparse` subcommands for the CLI
- `pytest` for tests
- `lxml` for XML parsing and writing
- standard-library HTTP tooling for Wikidata access

## Repository Integration

Projects such as `medieval-mss` and `mlgb` are expected to consume this package as an external dependency rather than copying the code into each repository.

### `pyproject.toml`

A consuming repository should declare the dependency in its `pyproject.toml`:

```toml
[project]
dependencies = [
  "lxml>=6.0.0",
  "tei-msdesc-authorities",
]

[tool.uv.sources]
"tei-msdesc-authorities" = { git = "https://github.com/msDesc/tei-msdesc-authorities" }
```

In practice, it is better to pin a tag or commit in workflow and release contexts rather than following the default branch indefinitely.

### GitHub Actions

A repository workflow can then install dependencies with `uv` and call the shared commands directly.

The expected use case is:

1. a cataloguer commits manuscript changes containing external `@ref` values
2. a GitHub Action runs `authorities enrich`
3. the workflow writes the updated manuscript and authority files
4. those changes are surfaced in a pull request for review

This makes the tool suitable not only for local maintenance but also for an editorial workflow in which authority normalization happens automatically during repository review.

Example GitHub Actions steps:

```yaml
- uses: actions/checkout@v4

- uses: astral-sh/setup-uv@v6

- name: Sync dependencies
  run: uv sync --dev

- name: Audit authority identifiers
  run: uv run authority-identifiers

- name: Reconcile existing authority links
  run: uv run authorities reconcile
```

For repositories that want to update manuscript data or authority files in CI, the same pattern applies:

```yaml
- name: Enrich authorities
  run: uv run authorities enrich collections/Example/Example_MS.xml
```

The package owns the `authorities` and `authority-identifiers` console scripts, so consumer repositories do not need local wrapper scripts for them.

A consuming repository may therefore want a workflow that:

- runs on pushes or pull requests touching manuscript or authority XML
- runs `uv run authorities enrich ...`
- commits the resulting authority/manuscript updates to a branch or bot-authored
  pull request
- optionally also runs `uv run authority-identifiers` as a safety check

## Repository Scope

This package is meant to be shared by `msDesc`-based TEI repositories that follow the same authority management conventions as those at the Bodleian Libraries. It is not intended as a general-purpose TEI toolkit.
