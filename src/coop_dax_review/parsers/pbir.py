"""Report parser: extract field references from PBIR visuals.

Lifts the core extraction logic from coop-data-doc's PBIR parser. We read
visual.json files in a .Report folder and extract table/column bindings to
feed rules that need report-awareness (e.g. broken field references, unused
measures).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from coop_dax_review.model import ReportReference

# Auto date/time artifacts we don't care about
_AUTO_DATETIME_RE = re.compile(r"^(localdatetable_|datetabletemplate_)[0-9a-f\-]{8,}$", re.IGNORECASE)


def _find_entity(obj) -> str | None:
    if isinstance(obj, dict):
        entity = obj.get("Entity") or obj.get("entity")
        if isinstance(entity, str):
            return entity
        for value in obj.values():
            found = _find_entity(value)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find_entity(value)
            if found is not None:
                return found
    return None


def _collect_bindings(obj, out: list[tuple[str, str]], parent_key: str = "") -> None:
    """Collect `(entity, property)` field references."""
    if isinstance(obj, dict):
        prop = obj.get("Property") or obj.get("property")
        if isinstance(prop, str):
            entity = _find_entity(obj)
            if entity:
                out.append((entity, prop))
        for key, value in obj.items():
            _collect_bindings(value, out, key)
    elif isinstance(obj, list):
        for value in obj:
            _collect_bindings(value, out, parent_key)


def _normalize_id(s: str) -> str:
    s = s.strip()
    while len(s) >= 2 and s[0] in "'\"[" and s[-1] in "'\"]":
        s = s[1:-1].strip()
    return s.lower()


def parse_report_references(report_dir: Path) -> list[ReportReference]:
    """Scan a .Report folder for field references."""
    refs: list[ReportReference] = []

    # Check definition.pbir to ensure it's a valid PBIR root (or just scan pages)
    pages_dir = report_dir / "definition" / "pages"
    if not pages_dir.is_dir():
        return refs

    for visual_json in pages_dir.rglob("visual.json"):
        try:
            data = json.loads(visual_json.read_text(encoding="utf-8-sig", errors="replace"), strict=False)
        except (OSError, json.JSONDecodeError):
            continue

        if not isinstance(data, dict):
            continue

        visual_obj = data.get("visual")
        if not isinstance(visual_obj, dict):
            continue

        bindings: list[tuple[str, str]] = []
        _collect_bindings(visual_obj, bindings)
        _collect_bindings(data.get("filterConfig") or {}, bindings)

        for entity, prop in bindings:
            if _AUTO_DATETIME_RE.match(entity):
                continue

            norm_entity = _normalize_id(entity)
            norm_prop = _normalize_id(prop)
            refs.append(
                ReportReference(
                    field=f"{norm_entity}[{norm_prop}]", visual_file=visual_json.as_posix(), line=0
                )
            )

    # Also parse definition/report.json for report-level filters, etc. if needed
    report_json = report_dir / "definition" / "report.json"
    if report_json.is_file():
        try:
            data = json.loads(report_json.read_text(encoding="utf-8-sig", errors="replace"), strict=False)
            if isinstance(data, dict):
                bindings: list[tuple[str, str]] = []
                _collect_bindings(data.get("filterConfig") or {}, bindings)
                for entity, prop in bindings:
                    if not _AUTO_DATETIME_RE.match(entity):
                        refs.append(
                            ReportReference(
                                field=f"{_normalize_id(entity)}[{_normalize_id(prop)}]",
                                visual_file=report_json.as_posix(),
                                line=0,
                            )
                        )
        except (OSError, json.JSONDecodeError):
            pass

    return refs
