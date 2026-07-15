"""Regression tests for the 20 issues confirmed by the adversarial review.

Each test name carries the issue's short title so a failure points back to the
exact bug it guards.
"""

import json
import os
import stat

import pytest

from coop_dax_review.cli import build_catalogs, discover_inputs
from coop_dax_review.model import ModelCatalog
from coop_dax_review.parsers.bim import parse_bim_model
from coop_dax_review.parsers.dax import bracket_refs, mask_dax
from coop_dax_review.parsers.tmdl import (
    _split_table_column,
    _unquote,
    group_tmdl_files,
    parse_tmdl_model,
)
from coop_dax_review.rules.helpers import line_at
from coop_dax_review.standards import RuleConfig, StandardsError

# -- #1 one unreadable .tmdl must not discard the other models -----------------


def test_unreadable_tmdl_degrades_only_its_own_model(tmp_path):
    good = tmp_path / "Good.SemanticModel" / "definition" / "tables"
    good.mkdir(parents=True)
    (good / "T.tmdl").write_text("table T\n\tmeasure BadName = 1\n", encoding="utf-8")
    bad_dir = tmp_path / "Bad.SemanticModel" / "definition" / "tables"
    bad_dir.mkdir(parents=True)
    bad = bad_dir / "T.tmdl"
    bad.write_text("table T\n", encoding="utf-8")
    os.chmod(bad, 0)
    if os.access(bad, os.R_OK):  # running as root / permissive FS — can't simulate
        pytest.skip("cannot make a file unreadable in this environment")
    try:
        tmdl, bim, pbit, pbix = discover_inputs((str(tmp_path),))
        catalogs = build_catalogs(tmdl, bim)
    finally:
        os.chmod(bad, stat.S_IRUSR | stat.S_IWUSR)
    names = {c.name for c in catalogs}
    assert "Good" in names  # readable model still analyzed
    # the unreadable file is reported as a diagnostic on its real path, not "(tmdl)"
    diags = [d for c in catalogs for d in c.diagnostics]
    assert any("Bad" in d.file and d.file != "(tmdl)" for d in diags)


def test_group_tmdl_files_returns_unreadable_separately(tmp_path):
    p = tmp_path / "T.tmdl"
    p.write_text("table T\n", encoding="utf-8")
    groups, unreadable = group_tmdl_files([p], {p: "T.tmdl"})
    # One group, keyed by the file's parent directory (the loose-file model
    # root) and named after that folder.
    assert [name for _root, name in groups] == [tmp_path.name]
    assert unreadable == []


# -- #2 JSON / report output is LF, never CRLF --------------------------------


def test_json_output_has_no_cr():
    from coop_dax_review import __version__
    from coop_dax_review.engine import run_rules
    from coop_dax_review.report import json_text

    result = run_rules([ModelCatalog(name="M", file="m.tmdl")], [])
    text = json_text(result, version=__version__, standards={"path": "p", "sha256": "x"})
    assert "\r" not in text


# -- #3 / #7 / #8 malformed .bim never discards the whole model ----------------


def test_bim_null_annotation_name_does_not_crash():
    cat = parse_bim_model(
        "m.bim",
        json.dumps(
            {
                "model": {
                    "tables": [
                        {"name": "DimDate", "annotations": [{"name": None}], "columns": [{"name": "Date"}]}
                    ]
                }
            }
        ),
    )
    assert cat.tables and cat.tables[0].name == "DimDate"


def test_bim_non_dict_partition_does_not_crash():
    cat = parse_bim_model(
        "m.bim", json.dumps({"model": {"tables": [{"name": "T", "partitions": [None, "oops"]}]}})
    )
    assert cat.tables[0].name == "T"


def test_bim_non_dict_column_or_measure_is_skipped():
    cat = parse_bim_model(
        "m.bim",
        json.dumps({"model": {"tables": [{"name": "T", "columns": ["Date", {"name": "Real"}]}]}}),
    )
    assert [c.name for c in cat.tables[0].columns] == ["Real"]


# -- #4 backslash-terminated string is masked (see also test_dax_utils) --------


def test_keyword_in_backslash_terminated_string_is_masked():
    masked = mask_dax('M = "path CALCULATE \\" + [Real]')
    assert "CALCULATE" not in masked
    assert [r.name for r in bracket_refs(masked)] == ["Real"]


# -- #5 / #14 line_at points at the real source line --------------------------


def test_line_at_multiline_measure_is_correct():
    tmdl = "table T\n\tmeasure 'A: M' =\n\t\tCALCULATE(\n\t\t\tCALCULATE([X])\n\t\t)\n"
    measure = parse_tmdl_model("M", {"t.tmdl": tmdl}).measures[0]
    inner = measure.dax.find("CALCULATE", measure.dax.find("CALCULATE") + 1)
    assert line_at(measure, inner) == 4  # inner CALCULATE is on file line 4, not 2/3


def test_line_at_accounts_for_interior_blank_lines():
    tmdl = "table T\n\tmeasure 'A: M' =\n\t\tSUM(T[x])\n\n\t\t+ CALCULATE(CALCULATE([Y]))\n"
    measure = parse_tmdl_model("M", {"t.tmdl": tmdl}).measures[0]
    inner = measure.dax.rfind("CALCULATE")
    assert line_at(measure, inner) == 5  # blank line on 4 must not be dropped


def test_measure_line_is_file_relative_for_second_table_block():
    # A file whose table starts below line 1: measure lines must be file-relative.
    tmdl = "// header\n\ntable T\n\tmeasure 'A: M' = SUM(T[x])\n"
    measure = parse_tmdl_model("M", {"t.tmdl": tmdl}).measures[0]
    assert measure.line == 4


# -- #6 discovery is case-insensitive on every OS -----------------------------


def test_discovery_finds_uppercase_extensions(tmp_path):
    (tmp_path / "Model.TMDL").write_text("table T\n", encoding="utf-8")
    (tmp_path / "Legacy.BIM").write_text("{}", encoding="utf-8")
    tmdl, bim, pbit, pbix = discover_inputs((str(tmp_path),))
    assert len(tmdl) == 1 and len(bim) == 1


# -- #9 dotted (quoted) table name splits on the right dot --------------------


def test_split_quoted_table_with_dot():
    assert _split_table_column("'Sales.Detail'.Amount") == ("Sales.Detail", "Amount")
    assert _split_table_column("DimDate.'Order Date'") == ("DimDate", "Order Date")
    assert _split_table_column("DimDate.Date") == ("DimDate", "Date")


# -- #10 TMDL cross_filter normalizes to single -------------------------------


def test_tmdl_crossfilter_normalized_to_single():
    tmdl = "model M\n\nrelationship r\n\tfromColumn: A.x\n\ttoColumn: B.y\n\tcrossFilteringBehavior: oneDirection\n"
    assert parse_tmdl_model("M", {"model.tmdl": tmdl}).relationships[0].cross_filter == "single"


# -- #11 multi-line calculated column captures expression + trailing props -----


def test_multiline_calculated_column():
    tmdl = "table T\n\tcolumn Margin =\n\t\tT[Rev] * 0.1\n\t\tdataType: double\n"
    col = parse_tmdl_model("M", {"t.tmdl": tmdl}).tables[0].columns[0]
    assert col.is_calculated and col.expression == "T[Rev] * 0.1" and col.data_type == "double"


def test_multiline_calculated_column_datacategory_marks_date_table():
    tmdl = "table DimDate\n\tcolumn DateKey =\n\t\tT[d]\n\t\tdataCategory: Time\n"
    assert parse_tmdl_model("M", {"d.tmdl": tmdl}).date_table == "DimDate"


# -- #15 invalid rules.yml severity is rejected, not silently dropped ----------


def test_invalid_config_severity_raises(tmp_path):
    cfg = tmp_path / "rules.yml"
    cfg.write_text("rules:\n  DAX-MEASURE-CATEGORY:\n    severity: critical\n", encoding="utf-8")
    with pytest.raises(StandardsError):
        RuleConfig.load(cfg)


def test_valid_config_severity_accepted(tmp_path):
    cfg = tmp_path / "rules.yml"
    cfg.write_text("rules:\n  DAX-MEASURE-CATEGORY:\n    severity: error\n", encoding="utf-8")
    assert RuleConfig.load(cfg).severity_overrides["DAX-MEASURE-CATEGORY"] == "error"


# -- #17 storage_mode tie-break is deterministic ------------------------------


def test_storage_mode_tiebreak_deterministic():
    from coop_dax_review.model import Table

    cat = ModelCatalog(
        name="M",
        tables=[Table(name="A", storage_mode="import"), Table(name="B", storage_mode="directQuery")],
    )
    assert cat.storage_mode == "directQuery"  # max(sorted(...)) — stable, not hash-dependent


# -- #18 doubled-quote escape in identifiers ----------------------------------


def test_unquote_collapses_doubled_quotes():
    assert _unquote("'O''Brien'") == "O'Brien"


def test_measure_name_with_apostrophe_round_trips():
    cat = parse_tmdl_model("M", {"t.tmdl": "table T\n\tmeasure 'O''Brien: M' = SUM(T[x])\n"})
    assert cat.measures[0].name == "O'Brien: M"


# -- #19 mixed tab/space indentation measures the body correctly ---------------


def test_mixed_indentation_measure_body_captured():
    # space-indented header, tab-indented body (one tab = 4 cols > 4 spaces)
    tmdl = "table T\n    measure 'A: M' =\n\t\tCALCULATE([X])\n"
    measure = parse_tmdl_model("M", {"t.tmdl": tmdl}).measures[0]
    assert "CALCULATE" in measure.dax


# -- #20 quoted table name containing '=' is not a calculated table -----------


def test_quoted_table_name_with_equals_not_calculated():
    cat = parse_tmdl_model("M", {"t.tmdl": "table 'A = B'\n\tcolumn X\n\t\tdataType: string\n"})
    assert cat.tables[0].name == "A = B" and cat.tables[0].is_calculated is False


def test_calculated_table_still_detected():
    cat = parse_tmdl_model("M", {"t.tmdl": "table MyCalc = SUMMARIZE(X)\n"})
    assert cat.tables[0].name == "MyCalc" and cat.tables[0].is_calculated is True


# == Build-phase verifier findings (Tier-2/3 + agent rules) ====================


def _rule(module, cat):
    from importlib import import_module

    from coop_dax_review.rules.base import RuleContext

    mod = import_module(f"coop_dax_review.rules.{module}")
    ctx = RuleContext(mod.RULE, cat)
    return mod.detect(ctx) if mod.RULE.kind == "agent" else mod.check(ctx)


def test_filter_col_vs_col_not_flagged(make_catalog):
    # FILTER(T, T[a] < T[b]) has no plain-column-filter equivalent -> legitimate.
    cat = make_catalog(
        measures=[("Sales: M", "CALCULATE([x], FILTER(DimC, DimC[SalePrice] < DimC[ListPrice]))")],
        tables=[("DimC", ["SalePrice", "ListPrice"])],
    )
    assert _rule("dax_filter_table_in_calculate", cat) == []


def test_filter_col_vs_constant_still_flagged(make_catalog):
    cat = make_catalog(
        measures=[("Sales: M", 'CALCULATE([x], FILTER(DimC, DimC[Seg] = "Enterprise"))')],
        tables=[("DimC", ["Seg"])],
    )
    assert len(_rule("dax_filter_table_in_calculate", cat)) == 1


def test_var_return_not_fooled_by_column_named_var(make_catalog):
    # A column literally named [VAR]/[RETURN] must not satisfy the VAR/RETURN check.
    cat = make_catalog(
        measures=[("Sales: M", "DIVIDE(SUM(t[Total VAR]), COUNT(t[Net RETURN]))")],
        tables=[("t", ["Total VAR", "Net RETURN"])],
    )
    assert len(_rule("dax_var_return", cat)) == 1


def test_measure_in_iterator_skips_column_name_collision(make_catalog):
    # [Qty] is both a measure and a column on the iterated table -> resolves to column.
    cat = make_catalog(
        measures=[("Qty", "SUM(Sales[Amount])"), ("Total", "SUMX(Sales, [Qty] * 2)")],
        tables=[("Sales", ["Qty", "Amount"])],
    )
    assert _rule("dax_measure_in_iterator", cat) == []
    assert _rule("dax_context_transition", cat) == []


def test_directlake_case_insensitive():
    from coop_dax_review.model import Column, ModelCatalog, Table

    cat = ModelCatalog(
        name="M",
        tables=[
            Table(
                name="F",
                storage_mode="DirectLake",  # capital D — parser stores verbatim
                columns=[Column(name="Margin", is_calculated=True)],
            )
        ],
    )
    assert len(_rule("dax_directlake_no_calc_col", cat)) == 1


def test_snowflake_ignores_inactive_relationships():
    from coop_dax_review.model import ModelCatalog, Relationship, Table

    cat = ModelCatalog(
        name="M",
        tables=[Table(name="Fact"), Table(name="DimA"), Table(name="DimB")],
        relationships=[
            Relationship(from_table="Fact", from_column="a", to_table="DimA", to_column="id"),
            Relationship(
                from_table="DimA", from_column="b", to_table="DimB", to_column="id", is_active=False
            ),
        ],
    )
    assert _rule("dax_snowflake", cat) == []  # the only dim->dim edge is inactive
