"""DAX-AUTO-DATETIME (§21): flag Power BI auto date/time artifacts."""

from importlib import import_module

from coop_dax_review.model import ModelCatalog, Table
from coop_dax_review.rules.base import RuleContext


def _run(cat):
    mod = import_module("coop_dax_review.rules.dax_auto_datetime")
    return mod.check(RuleContext(mod.RULE, cat))


def test_auto_datetime_tables_fire_once_per_model():
    cat = ModelCatalog(
        name="Sales",
        tables=[
            Table(name="FactSales"),
            Table(name="LocalDateTable_2b1e9f00-1111-2222-3333-444455556666"),
            Table(name="DateTableTemplate_aaaabbbb-cccc-dddd-eeee-ffff00001111"),
        ],
    )
    findings = _run(cat)
    assert len(findings) == 1  # one finding per model
    assert findings[0].object == "Sales"
    assert "2 auto date/time table(s)" in findings[0].message
    assert findings[0].rule_id == "DAX-AUTO-DATETIME"
    assert findings[0].severity == "warning"


def test_no_auto_datetime_tables_silent():
    cat = ModelCatalog(name="M", tables=[Table(name="FactSales"), Table(name="DimDate")])
    assert _run(cat) == []


def test_a_normal_table_named_like_date_is_not_flagged():
    # only the exact LocalDateTable_/DateTableTemplate_ prefixes count — a real
    # 'DateTable' or 'LocalDate' dimension must never trip.
    cat = ModelCatalog(name="M", tables=[Table(name="DateTable"), Table(name="LocalDate")])
    assert _run(cat) == []
