"""Regression tests for the round-2 adversarial review's confirmed findings.

Each test group carries the finding id it guards, so a failure points back to
the exact reviewed bug. Every rule-scope change pins BOTH directions: a fires
case and a compliant (does-NOT-fire) case.
"""

import json
from importlib import import_module
from pathlib import Path

from click.testing import CliRunner

from coop_dax_review.cli import cli
from coop_dax_review.finding import AgentReviewItem, Finding
from coop_dax_review.model import Column, ModelCatalog, Table
from coop_dax_review.report import SCHEMA_VERSION
from coop_dax_review.rules.base import RuleContext
from coop_dax_review.rules.helpers import has_block_comment


def _run(rule_module, catalog):
    mod = import_module(rule_module)
    ctx = RuleContext(mod.RULE, catalog)
    if mod.RULE.kind == "agent":
        return mod.detect(ctx)
    return mod.check(ctx)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


# -- blank-string-literals-ignores-line-comments -------------------------------
#
# An unpaired double-quote inside a `//` / `--` line comment (inch marks like
# 5/8") must not start a phantom string literal that swallows a following
# /* ... */ header — a §12-compliant measure would be flagged as undocumented.

_HEADERED_DAX = (
    '-- pipe measured in 5/8" units\n'
    "/* header block */\n"
    "VAR a = 1\n"
    "VAR b = 2\n"
    "VAR c = 3\n"
    'RETURN IF(a > b, "yes", "no")'
)


def test_quote_in_line_comment_does_not_swallow_block_header():
    assert has_block_comment(_HEADERED_DAX)


def test_complex_no_header_silent_with_line_comment_before_header(make_catalog):
    cat = make_catalog(measures=[("Sales: Pipe Len", _HEADERED_DAX)])
    assert _run("coop_dax_review.rules.dax_complex_no_header", cat) == []


def test_complex_no_header_still_fires_with_line_comment_but_no_header(make_catalog):
    dax = _HEADERED_DAX.replace("/* header block */\n", "")
    cat = make_catalog(measures=[("Sales: Pipe Len", dax)])
    assert len(_run("coop_dax_review.rules.dax_complex_no_header", cat)) == 1


def test_header_inside_string_is_still_not_a_header():
    assert not has_block_comment('VAR a = "/* not a header */"\nVAR b = 1\nVAR c = 2\nRETURN a')


# -- nested-calculate-flags-iterator-mediated-nesting ---------------------------
#
# §3 targets DIRECT nesting (CALCULATE as an argument of CALCULATE, hoistable
# into a VAR). A CALCULATE inside an iterator inside CALCULATE is the endorsed
# per-row context-transition idiom (§9) — hoisting it would change results.

_NESTED = "coop_dax_review.rules.dax_no_nested_calculate"


def test_direct_nested_calculate_still_fires(make_catalog):
    cat = make_catalog(measures=[("M", "CALCULATE(CALCULATE(SUM(F[x])) + 0, F[a] = 1)")])
    assert len(_run(_NESTED, cat)) == 1


def test_nested_calculate_via_scalar_function_still_fires(make_catalog):
    # ROUND is not an iterator: the inner CALCULATE is still hoistable into a VAR.
    cat = make_catalog(measures=[("M", "CALCULATE(ROUND(CALCULATE(SUM(F[x])), 2), F[a] = 1)")])
    assert len(_run(_NESTED, cat)) == 1


def test_iterator_mediated_calculate_does_not_fire(make_catalog):
    dax = (
        "CALCULATE(SUMX(VALUES(DimCustomer[CustomerId]), CALCULATE(SUM(FactSales[Revenue]))), "
        'FactSales[Channel] = "Web")'
    )
    cat = make_catalog(measures=[("Sales: Big Customers", dax)])
    assert _run(_NESTED, cat) == []


def test_averagex_mediated_calculate_does_not_fire(make_catalog):
    dax = "CALCULATE(AVERAGEX(VALUES(D[Id]), CALCULATE([Sales: Total])), F[Year] = 2026)"
    cat = make_catalog(measures=[("Sales: Avg", dax)])
    assert _run(_NESTED, cat) == []


def test_filter_mediated_calculate_does_not_fire(make_catalog):
    dax = "CALCULATE(SUM(F[x]), FILTER(ALL(F[c]), CALCULATE([Sales: Total]) > 0))"
    cat = make_catalog(measures=[("Sales: Filtered", dax)])
    assert _run(_NESTED, cat) == []


def test_iterator_below_the_inner_calculate_does_not_suppress(make_catalog):
    # The iterator lives INSIDE the inner CALCULATE — the nesting itself is
    # still direct, so it must still fire.
    cat = make_catalog(measures=[("M", "CALCULATE(CALCULATE(SUMX(F, F[x])), F[a] = 1)")])
    assert len(_run(_NESTED, cat)) == 1


# -- keepfilters-detection-wrong-both-directions --------------------------------
#
# Detection is per top-level filter argument: a sibling KEEPFILTERS must not
# suppress a bare predicate next to it (FN), and a comparison living inside a
# nested call (FILTER/ALL/MAX) is not a boolean shorthand filter (FP).

_KEEP = "coop_dax_review.rules.dax_keepfilters_needed"


def test_keepfilters_sibling_does_not_suppress_bare_predicate(make_catalog):
    cat = make_catalog(measures=[("Sales: A", "CALCULATE(SUM(T[x]), KEEPFILTERS(T[a] = 1), T[b] = 2)")])
    items = _run(_KEEP, cat)
    assert len(items) == 1
    assert "T[b] = 2" in items[0].note  # the offending predicate is named


def test_keepfilters_silent_when_comparison_only_inside_filter(make_catalog):
    cat = make_catalog(measures=[("Sales: A", "CALCULATE(SUM(T[x]), FILTER(ALL(T[a]), T[a] <= MAX(T[a])))")])
    assert _run(_KEEP, cat) == []


def test_keepfilters_quoted_table_predicate_still_detected(make_catalog):
    cat = make_catalog(measures=[("Sales: A", "CALCULATE(SUM(T[x]), 'Dim Cust'[Seg] = 1)")])
    assert len(_run(_KEEP, cat)) == 1


def test_keepfilters_parens_in_quoted_name_do_not_hide_sibling_predicate(make_catalog):
    # The '(' inside 'Sales (2024)' must not push the sibling predicate to
    # a phantom nested depth.
    cat = make_catalog(
        measures=[("Sales: A", "CALCULATE(SUM(T[x]), KEEPFILTERS('Sales (2024)'[a] = 1), T[b] = 2)")]
    )
    assert len(_run(_KEEP, cat)) == 1


# -- marked-date-table-ignores-calculated-columns --------------------------------
#
# Time intelligence living only in a calculated column has the same §8
# marked-Date-table requirement as in a measure.

_MDT = "coop_dax_review.rules.dax_marked_date_table"


def _calc_column_catalog(*, marked: bool) -> ModelCatalog:
    ytd = Column(
        name="SalesYTD",
        is_calculated=True,
        expression="TOTALYTD(SUM(FactSales[Revenue]), DimDate[Date])",
    )
    fact = Table(name="FactSales", columns=[Column(name="Revenue"), ytd])
    dim = Table(name="DimDate", columns=[Column(name="Date")], is_date_table=marked)
    return ModelCatalog(name="M", file="model.tmdl", tables=[fact, dim])


def test_marked_date_table_fires_on_calc_column_time_intel():
    findings = _run(_MDT, _calc_column_catalog(marked=False))
    assert len(findings) == 1
    assert "FactSales[SalesYTD]" in findings[0].message  # the offending object is named


def test_marked_date_table_silent_for_calc_column_when_marked():
    assert _run(_MDT, _calc_column_catalog(marked=True)) == []


def test_marked_date_table_ignores_time_intel_in_calc_column_comment():
    cat = _calc_column_catalog(marked=False)
    cat.tables[0].columns[1].expression = "FactSales[Revenue] -- TOTALYTD later"
    assert _run(_MDT, cat) == []


# -- fingerprint-cwd-dependent ----------------------------------------------------
#
# The fingerprint identity is (rule_id, model, object, message) — NO display
# path — so baselines and rules.yml ignore lists written from one cwd/machine
# still match from another. schema_version 2 marks the change.


def _finding(**overrides) -> Finding:
    base = dict(
        rule_id="DAX-USE-DIVIDE",
        severity="warning",
        model="Sales",
        file="proj/Sales.SemanticModel/definition/tables/T.tmdl",
        line=5,
        object="[M: Ratio]",
        message="use DIVIDE",
        standard_ref="§14",
    )
    base.update(overrides)
    return Finding(**base)


def test_fingerprint_is_display_path_independent():
    a = _finding()
    b = _finding(file="Sales.SemanticModel/definition/tables/T.tmdl", line=9)
    assert a.fingerprint() == b.fingerprint()


def test_fingerprint_still_distinguishes_identity_fields():
    assert _finding().fingerprint() != _finding(message="other").fingerprint()
    assert _finding().fingerprint() != _finding(object="[Other]").fingerprint()
    assert _finding().fingerprint() != _finding(model="Other").fingerprint()


def test_agent_item_fingerprint_is_display_path_independent():
    def item(file):
        return AgentReviewItem(
            rule_id="DAX-KEEPFILTERS-NEEDED",
            model="Sales",
            file=file,
            object="[M]",
            line=3,
            note="judge",
            standard_ref="§5",
        )

    assert item("proj/a.tmdl").fingerprint() == item("a.tmdl").fingerprint()


def test_schema_version_bumped_for_fingerprint_change():
    assert SCHEMA_VERSION == 2  # fingerprints changed: regenerate baselines/ignores once


_MODEL_TMDL = "table T\n\tcolumn A\n\t\tdataType: double\n\n\tmeasure 'M: Ratio' = T[A] / 2\n"


def test_baseline_written_from_one_cwd_suppresses_from_another(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    _write(proj / "S.SemanticModel" / "definition" / "tables" / "T.tmdl", _MODEL_TMDL)
    baseline = tmp_path / "baseline.json"
    runner = CliRunner()

    monkeypatch.chdir(proj)
    first = runner.invoke(cli, ["check", ".", "--write-baseline", str(baseline), "--format", "json"])
    assert first.exit_code == 0
    assert json.loads(first.stdout)["findings"]  # the model does produce findings

    monkeypatch.chdir(tmp_path)  # different cwd -> different display paths
    second = runner.invoke(cli, ["check", "proj", "--baseline", str(baseline), "--format", "json"])
    assert second.exit_code == 0
    payload = json.loads(second.stdout)
    assert payload["findings"] == []  # every baselined finding still matches
    assert not any(d["category"] == "baseline_stale" for d in payload["diagnostics"])


# -- agent_review suppression parity with coop-sql-review -----------------------
#
# All three suppression mechanisms (inline directives, --baseline, rules.yml
# ignore list) apply to agent_review items exactly as they do to findings —
# and an entry matching only an agent item is never reported stale.

_KEEPFILTERS_TMDL = (
    "table T\n"
    "\tcolumn x\n"
    "\t\tdataType: int64\n"
    "\tcolumn b\n"
    "\t\tdataType: int64\n\n"
    "\tmeasure 'Cat: Filtered' = CALCULATE(SUM(T[x]), T[b] = 2)\n"
    "\t\tformatString: #,0\n"
)


def _agent_model(tmp_path, text=_KEEPFILTERS_TMDL):
    _write(tmp_path / "S.SemanticModel" / "definition" / "tables" / "T.tmdl", text)
    return str(tmp_path)


def _check_json_at(*args):
    result = CliRunner().invoke(cli, ["check", *args, "--format", "json"])
    assert result.exit_code == 0
    return json.loads(result.stdout)


def test_agent_review_control_reports_keepfilters(tmp_path):
    payload = _check_json_at(_agent_model(tmp_path))
    assert any(a["rule_id"] == "DAX-KEEPFILTERS-NEEDED" for a in payload["agent_review"])


def test_inline_ignore_suppresses_agent_review_item(tmp_path):
    text = _KEEPFILTERS_TMDL.replace(
        "\tmeasure 'Cat: Filtered'",
        "\t// coop-dax-review:ignore DAX-KEEPFILTERS-NEEDED\n\tmeasure 'Cat: Filtered'",
    )
    payload = _check_json_at(_agent_model(tmp_path, text))
    assert all(a["rule_id"] != "DAX-KEEPFILTERS-NEEDED" for a in payload["agent_review"])


def test_inline_ignore_other_rule_keeps_agent_review_item(tmp_path):
    text = _KEEPFILTERS_TMDL.replace(
        "\tmeasure 'Cat: Filtered'",
        "\t// coop-dax-review:ignore DAX-USE-DIVIDE\n\tmeasure 'Cat: Filtered'",
    )
    payload = _check_json_at(_agent_model(tmp_path, text))
    assert any(a["rule_id"] == "DAX-KEEPFILTERS-NEEDED" for a in payload["agent_review"])


def test_baseline_suppresses_agent_review_item(tmp_path):
    root = _agent_model(tmp_path)
    bl = tmp_path / "bl.json"
    CliRunner().invoke(cli, ["check", root, "--write-baseline", str(bl)])
    payload = _check_json_at(root, "--baseline", str(bl))
    assert payload["agent_review"] == []
    # A baseline entry matching only an agent item is NOT stale.
    assert not any(d["category"] == "baseline_stale" for d in payload["diagnostics"])


def test_config_ignore_suppresses_agent_review_item_and_is_not_stale(tmp_path):
    root = _agent_model(tmp_path)
    payload = _check_json_at(root)
    fps = [a["fingerprint"] for a in payload["agent_review"] if a["rule_id"] == "DAX-KEEPFILTERS-NEEDED"]
    assert fps  # detected before suppression
    cfg = tmp_path / "rules.yml"
    cfg.write_text(f"ignore:\n  - fingerprint: {fps[0]}\n", encoding="utf-8")
    payload2 = _check_json_at(root, "--config", str(cfg))
    assert all(a["rule_id"] != "DAX-KEEPFILTERS-NEEDED" for a in payload2["agent_review"])
    assert not any(d["category"] == "ignore_stale" for d in payload2["diagnostics"])
