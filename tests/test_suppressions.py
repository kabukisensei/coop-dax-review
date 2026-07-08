"""Inline ignore directives + the fingerprint baseline, and fingerprint stability."""

import pytest

from coop_dax_review.finding import Finding
from coop_dax_review.suppressions import (
    BaselineError,
    is_inline_suppressed,
    load_baseline,
    scan_directives,
    write_baseline,
)


def test_scan_directives_parses_ids_and_stops_at_reason():
    text = "measure x = 1\n// coop-dax-review:ignore DAX-VAR-RETURN reason: legacy DAX-NOT-THIS\nmore\n"
    assert scan_directives(text) == {2: {"DAX-VAR-RETURN"}}  # the post-reason token is not an id


def test_scan_directives_bare_is_wildcard():
    assert scan_directives("// coop-dax-review:ignore\n") == {1: {"*"}}


def test_scan_directives_multiple_ids():
    assert scan_directives("// coop-dax-review:ignore DAX-A, DAX-B\n") == {1: {"DAX-A", "DAX-B"}}


def test_is_inline_suppressed_same_line_and_line_above():
    directives = {5: {"DAX-X"}}
    assert is_inline_suppressed("DAX-X", 5, directives)  # trailing on the same line
    assert is_inline_suppressed("DAX-X", 6, directives)  # directive on the line directly above
    assert not is_inline_suppressed("DAX-X", 7, directives)  # too far away
    assert not is_inline_suppressed("DAX-Y", 5, directives)  # a different rule
    assert not is_inline_suppressed("DAX-X", 0, directives)  # model-level finding (line 0)


def test_wildcard_directive_suppresses_any_rule():
    assert is_inline_suppressed("DAX-ANYTHING", 3, {3: {"*"}})


def test_fingerprint_is_line_independent_but_rule_sensitive():
    a = Finding("DAX-A", "warning", "M", "f.tmdl", 10, "[X]", "msg", "§1")
    moved = Finding("DAX-A", "warning", "M", "f.tmdl", 99, "[X]", "msg", "§1")  # only line differs
    other = Finding("DAX-B", "warning", "M", "f.tmdl", 10, "[X]", "msg", "§1")  # rule differs
    assert a.fingerprint() == moved.fingerprint()
    assert a.fingerprint() != other.fingerprint()


def test_baseline_roundtrip_is_deduped_and_sorted(tmp_path):
    path = tmp_path / "bl.json"
    assert write_baseline(path, ["zzz", "aaa", "aaa"]) == 2  # de-duplicated
    assert load_baseline(path) == {"aaa", "zzz"}
    assert '"aaa"' in path.read_text(encoding="utf-8")  # sorted, human-readable


def test_load_missing_or_malformed_baseline_raises(tmp_path):
    # a missing/corrupt baseline is now a loud BaselineError, not a silent empty
    # set (which used to flood every baselined finding back with no explanation).
    with pytest.raises(BaselineError, match="not found"):
        load_baseline(tmp_path / "nope.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(BaselineError, match="not valid JSON"):
        load_baseline(bad)


def test_load_baseline_rejects_a_different_tools_baseline(tmp_path):
    # the shim bakes in this tool's name, so a coop-sql-review baseline is rejected.
    path = tmp_path / "bl.json"
    path.write_text('{"tool": "coop-sql-review", "fingerprints": ["aaa"]}', encoding="utf-8")
    with pytest.raises(BaselineError, match="written by"):
        load_baseline(path)
