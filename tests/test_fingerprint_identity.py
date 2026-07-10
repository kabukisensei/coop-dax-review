"""The family fingerprint identity rule (schema_version 3, issue #14).

Identity = (rule_id, model, object-or-file-basename, fingerprint_key-or-message,
occurrence ordinal) — the SAME construction as coop-sql-review's schema 4
(which has no ``model`` component). Test names mirror the sql twin's
``tests/test_fingerprint_identity.py`` so the family contract stays visibly
in lockstep.
"""

from __future__ import annotations

import hashlib
import json
from importlib import import_module

from click.testing import CliRunner

from coop_dax_review.cli import cli
from coop_dax_review.finding import AgentReviewItem, Finding, assign_occurrences
from coop_dax_review.model import Measure, ModelCatalog, Table
from coop_dax_review.rules.base import RuleContext


def _rule_run(module: str, cat: ModelCatalog):
    mod = import_module(f"coop_dax_review.rules.{module}")
    return mod.check(RuleContext(mod.RULE, cat))


def _model_dir(root, n_measures: int, n_autodate: int = 0) -> None:
    """A minimal TMDL model: one Fact table with ``n_measures`` folderless
    measures (fires DAX-DISPLAY-FOLDERS past 5) and ``n_autodate`` auto
    date/time artifact tables (fires DAX-AUTO-DATETIME past 0)."""
    d = root / "M.SemanticModel" / "definition"
    (d / "tables").mkdir(parents=True, exist_ok=True)
    (d / "model.tmdl").write_text(
        "model M\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n", encoding="utf-8"
    )
    lines = ["table Fact", "", "\tcolumn Amount", "\t\tdataType: double", "\t\tsummarizeBy: sum", ""]
    for i in range(n_measures):
        lines += [f"\tmeasure 'Fact: M{i}' = SUM(Fact[Amount])", ""]
    (d / "tables" / "Fact.tmdl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for i in range(n_autodate):
        (d / "tables" / f"LocalDateTable_{i}.tmdl").write_text(
            f"table LocalDateTable_{i}\n\n\tcolumn Date\n\t\tdataType: dateTime\n", encoding="utf-8"
        )


def _json_run(*args) -> dict:
    return json.loads(CliRunner().invoke(cli, ["check", *args, "--format", "json"]).output)


def _by_rule(payload: dict, rule_id: str) -> list[dict]:
    return [f for f in payload["findings"] if f["rule_id"] == rule_id]


# --- the family construction, pinned exactly (mirrored in coop-sql-review) ----------


def test_family_identity_construction():
    # fingerprint = sha1("rule \x1f model \x1f object-or-basename \x1f key-or-message \x1f ordinal")[:12].
    # Pinned byte-for-byte so the two tools can never drift apart silently again.
    f = Finding("DAX-A", "warning", "Sales", "dir/f.tmdl", 10, "[M]", "msg", "§1", occurrence=2)
    expected = hashlib.sha1("\x1f".join(["DAX-A", "Sales", "[M]", "msg", "2"]).encode("utf-8")).hexdigest()[
        :12
    ]
    assert f.fingerprint() == expected
    # Empty object -> the file BASENAME stands in; fingerprint_key overrides the message.
    g = Finding("DAX-A", "warning", "Sales", "dir/f.tmdl", 10, "", "msg 27", "§1", fingerprint_key="stable")
    expected = hashlib.sha1(
        "\x1f".join(["DAX-A", "Sales", "f.tmdl", "stable", "0"]).encode("utf-8")
    ).hexdigest()[:12]
    assert g.fingerprint() == expected


def test_fingerprint_key_overrides_message():
    volatile = Finding(
        "DAX-A", "info", "M", "f.tmdl", 1, "Fact", "has 27 measures", "§1", fingerprint_key="core"
    )
    grown = Finding(
        "DAX-A", "info", "M", "f.tmdl", 1, "Fact", "has 28 measures", "§1", fingerprint_key="core"
    )
    assert volatile.fingerprint() == grown.fingerprint()  # message churn doesn't move identity
    keyless = Finding("DAX-A", "info", "M", "f.tmdl", 1, "Fact", "has 27 measures", "§1")
    assert keyless.fingerprint() != volatile.fingerprint()  # empty key -> message IS the identity


def test_occurrence_participates_in_fingerprint():
    first = Finding("DAX-A", "info", "M", "f.tmdl", 1, "o", "msg", "§1", occurrence=0)
    second = Finding("DAX-A", "info", "M", "f.tmdl", 9, "o", "msg", "§1", occurrence=1)
    assert first.fingerprint() != second.fingerprint()


def test_empty_object_falls_back_to_file_basename():
    # New at schema 3 (the sql twin's schema-3 fix adopted family-wide): object-less
    # findings in different files must not collapse to ONE fingerprint...
    a = Finding("DAX-A", "info", "M", "dir1/a.tmdl", 3, "", "constant", "§1")
    b = Finding("DAX-A", "info", "M", "dir2/b.tmdl", 9, "", "constant", "§1")
    assert a.fingerprint() != b.fingerprint()
    # ...but the SAME file seen from another cwd still matches (basename is cwd-free).
    a_other_cwd = Finding("DAX-A", "info", "M", "/abs/elsewhere/a.tmdl", 3, "", "constant", "§1")
    assert a.fingerprint() == a_other_cwd.fingerprint()


# --- the three volatile-message rules (issue #14) -------------------------------------


def _folderless(n: int) -> ModelCatalog:
    measures = [Measure(name=f"M{i}", dax="1", table="Fact", file="f.tmdl", line=1) for i in range(n)]
    return ModelCatalog(name="M", tables=[Table(name="Fact", file="f.tmdl")], measures=measures)


def test_display_folders_fingerprint_stable_as_model_grows():
    # issue #14: "table has {N} measures..." churned the fingerprint whenever ANY
    # measure was added. The identity core is now count-free.
    six = _rule_run("dax_display_folders", _folderless(6))
    seven = _rule_run("dax_display_folders", _folderless(7))
    assert len(six) == len(seven) == 1
    assert six[0].message != seven[0].message  # the human message still carries the count
    assert six[0].fingerprint_key == "no display folders"
    assert six[0].fingerprint() == seven[0].fingerprint()  # identity survives model growth


def _time_intel(users: int) -> ModelCatalog:
    measures = [
        Measure(name=f"YTD{i}", dax=f"TOTALYTD(SUM(F[A{i}]), 'Date'[Date])", table="F", file="f.tmdl")
        for i in range(users)
    ]
    return ModelCatalog(name="M", tables=[Table(name="F", file="f.tmdl")], measures=measures)


def test_marked_date_table_fingerprint_stable_as_users_change():
    # issue #14: the sorted example list + "(+N more)" churned on unrelated edits.
    one = _rule_run("dax_marked_date_table", _time_intel(1))
    seven = _rule_run("dax_marked_date_table", _time_intel(7))  # past the 5-example cap
    assert len(one) == len(seven) == 1
    assert one[0].message != seven[0].message
    assert one[0].fingerprint_key == "no marked date table"
    assert one[0].fingerprint() == seven[0].fingerprint()


def _autodate(artifacts: int) -> ModelCatalog:
    tables = [Table(name="Fact", file="f.tmdl")]
    tables += [Table(name=f"LocalDateTable_{i}", file=f"l{i}.tmdl") for i in range(artifacts)]
    return ModelCatalog(name="M", tables=tables)


def test_auto_datetime_fingerprint_stable_as_artifacts_change():
    # issue #14: the artifact count + example names churned as date columns came and went.
    one = _rule_run("dax_auto_datetime", _autodate(1))
    five = _rule_run("dax_auto_datetime", _autodate(5))  # past the 3-example cap
    assert len(one) == len(five) == 1
    assert one[0].message != five[0].message
    assert one[0].fingerprint_key == "auto date/time artifacts present"
    assert one[0].fingerprint() == five[0].fingerprint()


def test_volatile_fingerprint_survives_unrelated_edit_under_baseline(tmp_path):
    # END-TO-END (the issue's headline symptom): baseline a model whose only
    # DISPLAY-FOLDERS finding says "6 measures"; add a 7th measure; the finding must
    # STAY suppressed (and the baseline entry must not go stale) instead of flooding back.
    _model_dir(tmp_path, n_measures=6)
    bl = tmp_path / "bl.json"
    CliRunner().invoke(cli, ["check", str(tmp_path), "--write-baseline", str(bl)])
    _model_dir(tmp_path, n_measures=7)  # one unrelated (folderless) measure added
    payload = _json_run(str(tmp_path), "--baseline", str(bl))
    assert _by_rule(payload, "DAX-DISPLAY-FOLDERS") == []  # still suppressed
    stale = [d for d in payload["diagnostics"] if d["category"] == "baseline_stale"]
    assert stale == []  # ...and the entry still matches: no stale-baseline warning


# --- occurrence ordinals: assignment + the ratchet fix -------------------------------


def test_two_occurrences_get_distinct_fingerprints(tmp_path):
    # The dax collapse case: two copies of the SAME model (dev/prod) in one run — the
    # model name, object, and message coincide, so only the ordinal discriminates.
    _model_dir(tmp_path / "dev", n_measures=6)
    _model_dir(tmp_path / "prod", n_measures=6)
    payload = _json_run(str(tmp_path))
    folders = _by_rule(payload, "DAX-DISPLAY-FOLDERS")
    assert len(folders) == 2
    assert folders[0]["model"] == folders[1]["model"] == "M"
    assert folders[0]["message"] == folders[1]["message"]  # identical identity core...
    assert folders[0]["fingerprint"] != folders[1]["fingerprint"]  # ...distinct identities


def test_first_occurrence_keeps_ordinal_zero(tmp_path):
    # A single-occurrence group is just ordinal 0 — adding a second copy BELOW it
    # (sort order: dev < prod) must not move the first one's fingerprint.
    _model_dir(tmp_path / "dev", n_measures=6)
    only = _by_rule(_json_run(str(tmp_path)), "DAX-DISPLAY-FOLDERS")
    _model_dir(tmp_path / "prod", n_measures=6)
    both = _by_rule(_json_run(str(tmp_path)), "DAX-DISPLAY-FOLDERS")
    assert len(only) == 1 and len(both) == 2
    assert only[0]["fingerprint"] in {f["fingerprint"] for f in both}


def test_new_occurrence_not_suppressed_by_prior_baseline(tmp_path):
    # THE ratchet hole (family rule, coop-sql-review#16): baseline one copy of the
    # model, then add a same-named second copy -> its finding must surface, not vanish.
    _model_dir(tmp_path / "dev", n_measures=6)
    bl = tmp_path / "bl.json"
    CliRunner().invoke(cli, ["check", str(tmp_path), "--write-baseline", str(bl)])
    _model_dir(tmp_path / "prod", n_measures=6)
    payload = _json_run(str(tmp_path), "--baseline", str(bl))
    folders = _by_rule(payload, "DAX-DISPLAY-FOLDERS")
    assert len(folders) == 1  # dev's occurrence stays baselined...
    assert "prod/" in folders[0]["file"]  # ...and the NEW copy's occurrence is reported


def test_removing_earlier_occurrence_shifts_later_ordinals(tmp_path):
    # The documented trade-off (family rule): removing an EARLIER same-identity
    # sibling shifts the later ordinals — the survivor takes ordinal 0 (still
    # baselined) and the ordinal-1 entry goes stale LOUDLY, never silently.
    _model_dir(tmp_path / "dev", n_measures=6)
    _model_dir(tmp_path / "prod", n_measures=6)
    bl = tmp_path / "bl.json"
    CliRunner().invoke(cli, ["check", str(tmp_path), "--write-baseline", str(bl)])
    import shutil

    shutil.rmtree(tmp_path / "dev")  # drop the FIRST occurrence (sort order: dev < prod)
    payload = _json_run(str(tmp_path), "--baseline", str(bl))
    assert _by_rule(payload, "DAX-DISPLAY-FOLDERS") == []  # ordinal 0 still suppressed
    stale = [d for d in payload["diagnostics"] if d["category"] == "baseline_stale"]
    assert stale and "no longer match" in stale[0]["message"]  # the shifted entries are loud


def test_assign_occurrences_is_stable_and_group_scoped():
    # Ordinals count WITHIN one identity group; unrelated findings are untouched
    # (same list in -> same list out when ordinals already match, items reused).
    items = [
        Finding("DAX-A", "info", "M", "f.tmdl", 1, "o", "msg", "§1"),
        Finding("DAX-B", "info", "M", "f.tmdl", 2, "o", "msg", "§1"),  # different rule -> own group
        Finding("DAX-A", "info", "M", "f.tmdl", 3, "o", "msg", "§1"),
    ]
    stamped = assign_occurrences(items)
    assert [f.occurrence for f in stamped] == [0, 0, 1]
    assert stamped[0] is items[0]  # ordinal already correct -> the instance is reused
    again = assign_occurrences(stamped)
    assert again == stamped  # idempotent


def test_agent_item_family_identity_construction():
    # AgentReviewItem mirrors Finding exactly (note stands in for message).
    item = AgentReviewItem("DAX-X", "Sales", "dir/m.tmdl", "", 5, "note", "§5", occurrence=1)
    expected = hashlib.sha1(
        "\x1f".join(["DAX-X", "Sales", "m.tmdl", "note", "1"]).encode("utf-8")
    ).hexdigest()[:12]
    assert item.fingerprint() == expected
