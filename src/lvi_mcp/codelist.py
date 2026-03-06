"""Load and index the LVI-TUOTEOSA codelist JSON."""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Path relative to this file: src/lvi_mcp/codelist.py -> project root/data/
_CODELIST_PATH = Path(__file__).parent.parent.parent / "data" / "codelist_LVI-TUOTEOSA_Versio_1_0.json"


@dataclass
class CodeEntry:
    code: str
    pref_label_fi: str
    short_name: str | None
    definition_fi: str | None
    description_fi: str | None
    level: int
    parent_code: str | None
    raw: dict[str, Any] = field(repr=False)

    # Resolved after full load
    parent_label_fi: str | None = None
    grandparent_code: str | None = None
    grandparent_label_fi: str | None = None

    @property
    def search_text(self) -> str:
        parts = [
            self.pref_label_fi or "",
            self.short_name or "",
            self.definition_fi or "",
            self.description_fi or "",
            self.code,
        ]
        return " ".join(p for p in parts if p).lower()


def _normalize(text: str) -> str:
    """Lowercase + strip accents for fuzzy matching."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


class LviCodelist:
    """In-memory index of the LVI-TUOTEOSA codelist."""

    def __init__(self, path: Path = _CODELIST_PATH) -> None:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)

        self.by_code: dict[str, CodeEntry] = {}
        self.by_level: dict[int, list[CodeEntry]] = {1: [], 2: [], 3: []}

        for raw in data.get("codes", []):
            level = raw.get("hierarchyLevel", 3)
            parent_raw = raw.get("broaderCode")
            parent_code = parent_raw.get("codeValue") if parent_raw else None

            entry = CodeEntry(
                code=raw["codeValue"],
                pref_label_fi=raw.get("prefLabel", {}).get("fi", ""),
                short_name=raw.get("shortName"),
                definition_fi=raw.get("definition", {}).get("fi"),
                description_fi=raw.get("description", {}).get("fi"),
                level=level,
                parent_code=parent_code,
                raw=raw,
            )
            self.by_code[entry.code] = entry
            self.by_level.setdefault(level, []).append(entry)

        # Resolve parent / grandparent labels
        for entry in self.by_code.values():
            if entry.parent_code and entry.parent_code in self.by_code:
                parent = self.by_code[entry.parent_code]
                entry.parent_label_fi = parent.pref_label_fi
                if parent.parent_code and parent.parent_code in self.by_code:
                    gp = self.by_code[parent.parent_code]
                    entry.grandparent_code = gp.code
                    entry.grandparent_label_fi = gp.pref_label_fi

    # ------------------------------------------------------------------
    # Public search API
    # ------------------------------------------------------------------

    def get(self, code: str) -> CodeEntry | None:
        return self.by_code.get(code)

    def search(self, query: str, max_results: int = 10) -> list[tuple[CodeEntry, float]]:
        """Return (entry, score) pairs sorted by descending score.

        Scoring tiers:
        4 — exact code match
        3 — exact shortName match (case-insensitive)
        2 — exact prefLabel match (case-insensitive, normalized)
        1 — substring match in prefLabel or shortName
        0.5 — substring match in definition
        """
        q = query.strip()
        q_lower = q.lower()
        q_norm = _normalize(q)

        results: list[tuple[CodeEntry, float]] = []

        for entry in self.by_code.values():
            score = 0.0

            if entry.code.lower() == q_lower:
                score = 4.0
            elif entry.short_name and entry.short_name.lower() == q_lower:
                score = 3.0
            elif _normalize(entry.pref_label_fi) == q_norm:
                score = 2.0
            elif q_norm in _normalize(entry.pref_label_fi) or (
                entry.short_name and q_norm in _normalize(entry.short_name)
            ):
                score = 1.0
            elif entry.definition_fi and q_norm in _normalize(entry.definition_fi):
                score = 0.5

            if score > 0:
                results.append((entry, score))

        results.sort(key=lambda x: (-x[1], x[0].code))
        return results[:max_results]

    def classify_from_text(
        self,
        name: str | None,
        object_type: str | None,
        description: str | None,
        extra_props: dict[str, str] | None = None,
        max_results: int = 5,
    ) -> list[tuple[CodeEntry, float, str]]:
        """Return (entry, score, reasoning) for leaf-level (level 3) entries only."""
        candidates_text = " ".join(
            filter(None, [name, object_type, description, *(extra_props or {}).values()])
        )
        q_norm = _normalize(candidates_text)

        results: list[tuple[CodeEntry, float, str]] = []

        for entry in self.by_level.get(3, []):
            score = 0.0
            reasons: list[str] = []

            label_norm = _normalize(entry.pref_label_fi)
            sn_norm = _normalize(entry.short_name) if entry.short_name else ""
            def_norm = _normalize(entry.definition_fi) if entry.definition_fi else ""

            # Exact short name
            if sn_norm and sn_norm in q_norm:
                score += 3.0
                reasons.append(f"shortName '{entry.short_name}' found in element text")

            # prefLabel substring in query or query substring in prefLabel
            words = label_norm.split()
            matching_words = [w for w in words if len(w) > 3 and w in q_norm]
            if len(matching_words) == len(words) and words:
                score += 2.0
                reasons.append(f"prefLabel '{entry.pref_label_fi}' fully matched")
            elif matching_words:
                ratio = len(matching_words) / max(len(words), 1)
                score += ratio * 1.5
                reasons.append(
                    f"prefLabel partial match: {matching_words}"
                )

            # Definition keyword match
            if def_norm:
                def_words = [w for w in def_norm.split() if len(w) > 4]
                def_matching = [w for w in def_words if w in q_norm]
                if def_matching:
                    score += 0.3 * len(def_matching)
                    reasons.append(f"definition keywords: {def_matching[:3]}")

            if score > 0:
                reasoning = "; ".join(reasons) if reasons else "keyword match"
                results.append((entry, round(score, 3), reasoning))

        results.sort(key=lambda x: (-x[1], x[0].code))
        return results[:max_results]


# Module-level singleton (loaded once at import time)
_codelist: LviCodelist | None = None


def get_codelist() -> LviCodelist:
    global _codelist
    if _codelist is None:
        _codelist = LviCodelist()
    return _codelist
