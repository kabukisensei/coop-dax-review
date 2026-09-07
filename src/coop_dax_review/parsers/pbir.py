"""Report parser: extract field references from PBIR visuals.

Lifts the core extraction logic from coop-data-doc's PBIR parser. We read
visual.json files in a .Report folder and extract table/column bindings to
feed rules that need report-awareness (e.g. broken field references, unused
measures).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from coop_dax_review.diagnostics import PBIR_PARSE_FAILED, Diagnostic
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


@dataclass
class ReportScanResult:
    """Structured PBIR coverage and the references recovered from it."""

    references: list[ReportReference] = field(default_factory=list)
    files_attempted: int = 0
    files_parsed: int = 0
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def status(self) -> str:
        if not self.diagnostics:
            return "complete"
        if self.files_parsed == 0:
            return "failed"
        return "partial"


def _read_json(path: Path, result: ReportScanResult) -> dict | None:
    """Read one PBIR JSON object, recording any loss of evidence."""
    result.files_attempted += 1
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        result.diagnostics.append(
            Diagnostic(
                severity="error",
                category=PBIR_PARSE_FAILED,
                file=path.as_posix(),
                line=0,
                message=f"could not decode PBIR JSON {path.as_posix()} - the file must be valid UTF-8",
            )
        )
        return None
    except OSError as exc:
        reason = exc.strerror or str(exc)
        result.diagnostics.append(
            Diagnostic(
                severity="error",
                category=PBIR_PARSE_FAILED,
                file=path.as_posix(),
                line=0,
                message=f"could not read PBIR JSON {path.as_posix()}: {reason}",
            )
        )
        return None

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        result.diagnostics.append(
            Diagnostic(
                severity="error",
                category=PBIR_PARSE_FAILED,
                file=path.as_posix(),
                line=exc.lineno,
                message=(
                    f"could not parse PBIR JSON {path.as_posix()}: {exc.msg} "
                    f"at line {exc.lineno}, column {exc.colno}"
                ),
            )
        )
        return None

    if not isinstance(data, dict):
        result.diagnostics.append(
            Diagnostic(
                severity="error",
                category=PBIR_PARSE_FAILED,
                file=path.as_posix(),
                line=0,
                message=f"could not parse PBIR JSON {path.as_posix()}: root must be a JSON object",
            )
        )
        return None

    result.files_parsed += 1
    return data


def _append_bindings(data: object, path: Path, refs: list[ReportReference]) -> None:
    bindings: list[tuple[str, str]] = []
    _collect_bindings(data, bindings)
    for entity, prop in bindings:
        if _AUTO_DATETIME_RE.match(entity):
            continue
        refs.append(
            ReportReference(
                field=f"{_normalize_id(entity)}[{_normalize_id(prop)}]",
                visual_file=path.as_posix(),
                line=0,
            )
        )


def parse_report_references(report_dir: Path) -> ReportScanResult:
    """Scan a .Report folder with explicit evidence-completeness metadata."""
    result = ReportScanResult()

    pages_dir = report_dir / "definition" / "pages"
    if not pages_dir.is_dir():
        result.diagnostics.append(
            Diagnostic(
                severity="error",
                category=PBIR_PARSE_FAILED,
                file=pages_dir.as_posix(),
                line=0,
                message=f"could not scan PBIR report {report_dir.as_posix()}: definition/pages is missing",
            )
        )
        return result

    for visual_json in sorted(pages_dir.rglob("visual.json"), key=lambda path: path.as_posix()):
        data = _read_json(visual_json, result)
        if data is None:
            continue
        visual_obj = data.get("visual")
        if not isinstance(visual_obj, dict):
            result.files_parsed -= 1
            result.diagnostics.append(
                Diagnostic(
                    severity="error",
                    category=PBIR_PARSE_FAILED,
                    file=visual_json.as_posix(),
                    line=0,
                    message=(
                        f"could not parse PBIR visual {visual_json.as_posix()}: "
                        "the 'visual' value must be a JSON object"
                    ),
                )
            )
            continue
        _append_bindings(visual_obj, visual_json, result.references)
        _append_bindings(data.get("filterConfig") or {}, visual_json, result.references)

    # Also parse definition/report.json for report-level filters, etc. if needed
    report_json = report_dir / "definition" / "report.json"
    if report_json.is_file():
        data = _read_json(report_json, result)
        if data is not None:
            _append_bindings(data.get("filterConfig") or {}, report_json, result.references)

    # Stable, cross-platform ordering and deduplication. Keeping the source file
    # in the key preserves one actionable broken-reference location per visual.
    unique = {(ref.visual_file, ref.field, ref.line): ref for ref in result.references}
    result.references = [unique[key] for key in sorted(unique)]
    result.diagnostics.sort(key=lambda diagnostic: diagnostic.sort_key())
    return result
