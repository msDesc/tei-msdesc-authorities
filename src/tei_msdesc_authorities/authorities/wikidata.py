"""Minimal Wikidata client used by enrichment and reconciliation workflows."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request


class WikidataClient:
    """Fetch and cache Wikidata entities using the Action API.

    The client deliberately stays small and dependency-light. It batches
    ``wbgetentities`` requests, retries on ``429`` responses, and keeps a
    per-run in-memory cache so that related entities and property records are
    not fetched repeatedly.
    """

    def __init__(self, *, no_fetch: bool) -> None:
        self.no_fetch = no_fetch
        self._entity_cache: dict[str, dict[str, object] | None] = {}
        self._last_error: str | None = None

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def get_entities(
        self, qids: list[str] | tuple[str, ...] | set[str]
    ) -> dict[str, dict[str, object] | None]:
        """Fetch one or more Wikidata entities, preserving request order."""

        normalized: list[str] = []
        for qid in qids:
            upper = qid.upper()
            if upper and upper not in normalized:
                normalized.append(upper)
        if not normalized:
            return {}
        if self.no_fetch:
            self._last_error = "Fetching disabled by --no-fetch"
            for qid in normalized:
                self._entity_cache.setdefault(qid, None)
            return {qid: self._entity_cache[qid] for qid in normalized}

        missing = [qid for qid in normalized if qid not in self._entity_cache]
        for start in range(0, len(missing), 50):
            chunk = missing[start : start + 50]
            query = urllib.parse.urlencode(
                {
                    "action": "wbgetentities",
                    "ids": "|".join(chunk),
                    "format": "json",
                    "props": "labels|aliases|claims",
                }
            )
            url = f"https://www.wikidata.org/w/api.php?{query}"
            payload = self._request_json(url)
            if not isinstance(payload, dict):
                for qid in chunk:
                    self._entity_cache[qid] = None
                continue
            entities = payload.get("entities")
            if not isinstance(entities, dict):
                for qid in chunk:
                    self._entity_cache[qid] = None
                continue
            for qid in chunk:
                entity = entities.get(qid)
                self._entity_cache[qid] = (
                    entity if isinstance(entity, dict) else None
                )

        return {qid: self._entity_cache.get(qid) for qid in normalized}

    def _request_json(self, url: str) -> dict[str, object] | None:
        """Fetch JSON from Wikidata with basic retry/backoff behaviour."""

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "medieval-mss-authority-enrichment/1.1 (+https://github.com/medieval-mss)",
                "Accept": "application/json",
            },
            method="GET",
        )
        self._last_error = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=20) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < 2:
                    retry_after = (
                        exc.headers.get("Retry-After") if exc.headers else None
                    )
                    try:
                        delay = (
                            float(retry_after)
                            if retry_after
                            else float(2**attempt)
                        )
                    except ValueError:
                        delay = float(2**attempt)
                    time.sleep(delay)
                    continue
                self._last_error = f"HTTP {exc.code} from Wikidata"
                return None
            except urllib.error.URLError as exc:
                reason = getattr(exc, "reason", exc)
                self._last_error = (
                    f"Network error talking to Wikidata: {reason}"
                )
                return None
            except TimeoutError:
                self._last_error = "Timed out talking to Wikidata"
                return None
            except json.JSONDecodeError:
                self._last_error = "Invalid JSON returned by Wikidata"
                return None
        self._last_error = "Too many requests from Wikidata"
        return None

    def get_entity(self, qid: str) -> dict[str, object] | None:
        qid = qid.upper()
        return self.get_entities([qid]).get(qid)

    def search_entities(
        self, query: str, *, language: str = "en", limit: int = 5
    ) -> list[dict[str, object]]:
        """Run a ``wbsearchentities`` query and return raw result objects."""

        if self.no_fetch or not query.strip():
            return []
        request_query = urllib.parse.urlencode(
            {
                "action": "wbsearchentities",
                "search": query,
                "language": language,
                "format": "json",
                "type": "item",
                "limit": str(limit),
            }
        )
        url = f"https://www.wikidata.org/w/api.php?{request_query}"
        payload = self._request_json(url)
        try:
            if not isinstance(payload, dict):
                return []
            results = payload.get("search", [])
            if isinstance(results, list):
                return [
                    result for result in results if isinstance(result, dict)
                ]
        except KeyError:
            return []
        return []
