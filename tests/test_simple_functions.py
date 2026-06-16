"""Tests for DAX-SIMPLE-FUNCTIONS (§10): flag measures that use CALCULATE 3+ times."""

from __future__ import annotations

from importlib import import_module

from coop_dax_review.rules.base import RuleContext


def _run(cat):
    mod = import_module("coop_dax_review.rules.dax_simple_functions")
    ctx = RuleContext(mod.RULE, cat)
    return mod.detect(ctx) if mod.RULE.kind == "agent" else mod.check(ctx)


def test_three_calculates_fires_once(make_catalog):
    # Three CALCULATE calls yield exactly one review item (capped per measure).
    dax = (
        "VAR A = CALCULATE([X], T[c] = 1)\n"
        "VAR B = CALCULATE([X], T[c] = 2)\n"
        "VAR C = CALCULATE([X], T[c] = 3)\n"
        "RETURN A + B + C"
    )
    cat = make_catalog(measures=[("M: Three", dax)])
    items = _run(cat)
    assert len(items) == 1
    assert items[0].object == "[M: Three]"


def test_standards_good_two_calculate_pattern_silent(make_catalog):
    # §3 Good example: two separate CALCULATE in distinct VARs is the endorsed
    # alternative to nesting — it must NOT be flagged as over-using CALCULATE.
    dax = (
        "VAR CurrentYear = CALCULATE([Sales: Total Revenue], DATESYTD(DimDate[Date]))\n"
        "VAR PreviousYear = CALCULATE([Sales: Total Revenue], SAMEPERIODLASTYEAR(DimDate[Date]))\n"
        "RETURN CurrentYear - PreviousYear"
    )
    cat = make_catalog(measures=[("Sales: Revenue YTD", dax)])
    assert _run(cat) == []


def test_single_calculate_silent(make_catalog):
    # §4 Good example: one justified CALCULATE must not fire.
    dax = 'CALCULATE([Sales: Total Revenue], DimCustomer[MarketSegment] = "Enterprise")'
    cat = make_catalog(measures=[("Sales: Enterprise Revenue", dax)])
    assert _run(cat) == []


def test_trivial_sum_silent(make_catalog):
    cat = make_catalog(measures=[("Sales: Total Revenue", "SUM(FactSales[Revenue])")])
    assert _run(cat) == []


def test_calculate_in_comment_or_string_does_not_count(make_catalog):
    # Only one real CALCULATE; the others live in a comment and a string literal.
    dax = (
        "-- old approach used CALCULATE(CALCULATE(...)) which we removed\n"
        'VAR Label = "CALCULATE here is just text"\n'
        "VAR R = CALCULATE([X], T[c] = 1)\n"
        "RETURN R"
    )
    cat = make_catalog(measures=[("M: Masked", dax)])
    assert _run(cat) == []
