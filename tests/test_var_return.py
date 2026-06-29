"""DAX-VAR-RETURN (§2): non-trivial measures should use VAR/RETURN."""

from importlib import import_module

from coop_dax_review.rules.base import RuleContext


def _run(cat):
    mod = import_module("coop_dax_review.rules.dax_var_return")
    ctx = RuleContext(mod.RULE, cat)
    return mod.detect(ctx) if mod.RULE.kind == "agent" else mod.check(ctx)


# The §2 Bad example: a dense one-liner with no VAR/RETURN.
_BAD = (
    "CALCULATE(SUM(FactSales[Revenue]), DATESBETWEEN(DimDate[Date], MIN(DimDate[Date]), MAX(DimDate[Date])))"
)

# The §2 Good example: VAR/RETURN with named intermediate steps.
_GOOD = (
    "VAR SelectedPeriod =\n"
    "    DATESBETWEEN(\n"
    "        DimDate[Date],\n"
    "        MIN(DimDate[Date]),\n"
    "        MAX(DimDate[Date])\n"
    "    )\n"
    "VAR Result =\n"
    "    CALCULATE(\n"
    "        SUM(FactSales[Revenue]),\n"
    "        SelectedPeriod\n"
    "    )\n"
    "RETURN\n"
    "    Result"
)


def test_bad_example_fires(make_catalog):
    cat = make_catalog(measures=[("Sales: Total Revenue", _BAD)])
    findings = _run(cat)
    assert len(findings) == 1
    assert findings[0].object == "[Sales: Total Revenue]"
    assert findings[0].line == 1  # measure.line


def test_good_example_silent(make_catalog):
    cat = make_catalog(measures=[("Sales: Total Revenue", _GOOD)])
    assert _run(cat) == []


def test_trivial_sum_silent(make_catalog):
    cat = make_catalog(measures=[("Sales: Total Revenue", "SUM(FactSales[Revenue])")])
    assert _run(cat) == []


def test_single_calculate_silent(make_catalog):
    # Two calls (CALCULATE + SUM) is below the threshold -> stays silent.
    cat = make_catalog(measures=[("Sales: Filtered", "CALCULATE(SUM(FactSales[Revenue]))")])
    assert _run(cat) == []


def test_scalar_constant_silent(make_catalog):
    cat = make_catalog(measures=[("Sales: One", "1")])
    assert _run(cat) == []


def test_calls_in_comment_or_string_do_not_count(make_catalog):
    # Function-looking text inside a string/comment is masked, so it must not
    # push a trivial measure over the threshold.
    dax = "SUM(FactSales[Revenue]) -- CALCULATE( MIN( MAX(\n + 0 // FILTER( ADDCOLUMNS("
    cat = make_catalog(measures=[("Sales: Total Revenue", dax)])
    assert _run(cat) == []


def test_non_trivial_without_var_fires(make_catalog):
    # Three distinct calls, no VAR/RETURN.
    cat = make_catalog(measures=[("Sales: Mix", "DIVIDE(SUM(t[a]), COUNT(t[b]))")])
    assert len(_run(cat)) == 1


def test_paren_in_column_name_not_counted_as_call(make_catalog):
    # A '(' inside a column name like [Amount (USD)] must not be miscounted as a
    # phantom function call: this is a trivial two-call measure and must stay
    # silent (regression — it was counted as 3 calls and fired).
    cat = make_catalog(measures=[("Sales: Total", "CALCULATE(SUM(Sales[Amount (USD)]))")])
    assert _run(cat) == []
