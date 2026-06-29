"""Tests for DAX-COMPLEX-NO-HEADER (§12)."""

from importlib import import_module

from coop_dax_review.rules.base import RuleContext


def _run(cat):
    mod = import_module("coop_dax_review.rules.dax_complex_no_header")
    ctx = RuleContext(mod.RULE, cat)
    return mod.detect(ctx) if mod.RULE.kind == "agent" else mod.check(ctx)


_COMPLEX_DAX = """
VAR CurrentYear =
    CALCULATE([Sales: Total Revenue], DATESYTD(DimDate[Date]))
VAR PreviousYear =
    CALCULATE([Sales: Total Revenue], SAMEPERIODLASTYEAR(DimDate[Date]))
VAR Result =
    CurrentYear - PreviousYear
RETURN
    Result
""".strip()

_HEADER = """/*
  Measure: [Sales: Revenue YTD]
  Purpose: Year-to-date revenue versus prior year
  Context: Works in any filter context
  Dependencies: FactSales[Revenue], DimDate[Date]
  Author: Aaron Jennings
  Date: 2026-06-01
*/
"""


def test_fires(make_catalog):
    # Complex (3 VARs) and no /* */ header -> fires.
    cat = make_catalog(measures=[("Sales: Revenue YTD", _COMPLEX_DAX)])
    out = _run(cat)
    assert len(out) == 1
    assert out[0].object == "[Sales: Revenue YTD]"
    assert out[0].severity == "info"
    assert out[0].standard_ref == "§12"


def test_simple_silent(make_catalog):
    # Few VARs -> not complex -> no header expected.
    simple = "VAR R = SUM(FactSales[Revenue])\nRETURN R"
    cat = make_catalog(measures=[("Sales: Total Revenue", simple)])
    assert _run(cat) == []


def test_no_vars_silent(make_catalog):
    cat = make_catalog(measures=[("Sales: Total", "SUM(FactSales[Revenue])")])
    assert _run(cat) == []


def test_header_silences_complex(make_catalog):
    # The §12 header block in front of a complex body must NOT fire.
    cat = make_catalog(measures=[("Sales: Revenue YTD", _HEADER + _COMPLEX_DAX)])
    assert _run(cat) == []


def test_var_keyword_in_string_not_counted(make_catalog):
    # "VAR" mentions inside a comment/string must not push a simple measure
    # over the complexity threshold (we scan masked DAX).
    dax = 'VAR Label = "this VAR VAR VAR is just text"\n// VAR VAR VAR in a comment too\nRETURN Label'
    cat = make_catalog(measures=[("Sales: Label", dax)])
    assert _run(cat) == []


def test_block_comment_inside_string_does_not_count_as_header(make_catalog):
    # A `/* ... */` substring that lives inside a string literal is NOT a
    # documentation header, so a complex measure with such a string must still
    # fire (regression: it was wrongly treated as already-documented).
    dax = 'VAR a = 1\nVAR b = 2\nVAR c = 3\nRETURN "label /* not a header */ end"'
    cat = make_catalog(measures=[("Sales: Labeled", dax)])
    assert len(_run(cat)) == 1


def test_points_at_declaration_line(make_catalog):
    from coop_dax_review.model import Measure, ModelCatalog

    cat = ModelCatalog(name="T", file="T.tmdl")
    cat.measures.append(
        Measure(name="Sales: Revenue YTD", dax=_COMPLEX_DAX, table="FactSales", file="T.tmdl", line=42)
    )
    out = _run(cat)
    assert len(out) == 1
    assert out[0].line == 42
