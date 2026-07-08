"""Calculation-group support (issue #8): parse calculationGroup/calculationItem
and lint their DAX with the rules whose semantics clearly transfer."""

import json
from importlib import import_module

from coop_dax_review.engine import run_rules
from coop_dax_review.model import CalculationItem, ModelCatalog, Table
from coop_dax_review.parsers.bim import parse_bim_model
from coop_dax_review.parsers.tmdl import parse_tmdl_model
from coop_dax_review.rules import all_rules
from coop_dax_review.rules.base import RuleContext

CALC_GROUP_TMDL = (
    "table 'Time Intelligence'\n"
    "\tcalculationGroup\n"
    "\n"
    "\tcalculationItem Current = SELECTEDMEASURE()\n"
    "\n"
    "\tcalculationItem YoY =\n"
    "\t\tCALCULATE(SELECTEDMEASURE(), SAMEPERIODLASTYEAR(DimDate[Date]))\n"
    "\n"
    "\tcolumn 'Time Calculation'\n"
    "\t\tdataType: string\n"
)


def _run(module, cat):
    mod = import_module(f"coop_dax_review.rules.{module}")
    ctx = RuleContext(mod.RULE, cat)
    return mod.detect(ctx) if mod.RULE.kind == "agent" else mod.check(ctx)


# -- parsing -----------------------------------------------------------------


def test_tmdl_calculation_items_parsed_not_as_measures():
    cat = parse_tmdl_model("m", {"m/definition/tables/TI.tmdl": CALC_GROUP_TMDL})
    items = {c.name: c for c in cat.calculation_items}
    assert set(items) == {"Current", "YoY"}
    assert items["Current"].dax == "SELECTEDMEASURE()"
    assert "SAMEPERIODLASTYEAR" in items["YoY"].dax
    assert items["Current"].line == 4 and items["YoY"].line == 6
    assert items["YoY"].table == "Time Intelligence"
    # naming rules must never see item names as measures
    assert cat.measures == []


def test_bim_calculation_items_parsed():
    model = {
        "name": "M",
        "model": {
            "tables": [
                {
                    "name": "Time Intelligence",
                    "calculationGroup": {
                        "calculationItems": [
                            {"name": "Current", "expression": "SELECTEDMEASURE()"},
                            {
                                "name": "YoY",
                                "expression": "CALCULATE(SELECTEDMEASURE(), SAMEPERIODLASTYEAR(DimDate[Date]))",
                            },
                        ]
                    },
                }
            ]
        },
    }
    cat = parse_bim_model("m.bim", json.dumps(model))
    items = {c.name: c for c in cat.calculation_items}
    assert set(items) == {"Current", "YoY"}
    assert cat.measures == []


# -- linting -----------------------------------------------------------------


def _catalog_with_item(dax: str) -> ModelCatalog:
    return ModelCatalog(
        name="M",
        tables=[Table(name="TI", file="ti.tmdl")],
        calculation_items=[CalculationItem(name="It", dax=dax, table="TI", file="ti.tmdl", line=3)],
    )


def test_divide_fires_on_calculation_item():
    (f,) = _run("dax_use_divide", _catalog_with_item("SELECTEDMEASURE() / 2"))
    assert f.object == "TI[It]" and f.line == 3


def test_nested_calculate_fires_on_calculation_item():
    (f,) = _run("dax_no_nested_calculate", _catalog_with_item("CALCULATE(CALCULATE(SELECTEDMEASURE()))"))
    assert f.object == "TI[It]"


def test_compliant_calculation_item_silent():
    cat = _catalog_with_item("DIVIDE(SELECTEDMEASURE(), 2)")
    assert _run("dax_use_divide", cat) == []
    assert _run("dax_no_nested_calculate", cat) == []


def test_time_intel_in_calculation_item_triggers_marked_date_table():
    # a calc item using SAMEPERIODLASTYEAR needs a marked Date table (§8).
    cat = _catalog_with_item("CALCULATE(SELECTEDMEASURE(), SAMEPERIODLASTYEAR(DimDate[Date]))")
    findings = _run("dax_marked_date_table", cat)
    assert len(findings) == 1
    assert "TI[It]" in findings[0].message


def test_marked_date_table_silent_when_group_has_no_time_intel():
    cat = _catalog_with_item("SELECTEDMEASURE() * 2")
    assert _run("dax_marked_date_table", cat) == []


def test_calc_group_end_to_end_bad_item_flagged():
    cat = parse_tmdl_model(
        "m",
        {
            "m/definition/tables/TI.tmdl": CALC_GROUP_TMDL.replace(
                "Current = SELECTEDMEASURE()", "Bad = SELECTEDMEASURE() / 2"
            )
        },
    )
    result = run_rules([cat], all_rules())
    ids = {(f.rule_id, f.object) for f in result.findings}
    assert ("DAX-USE-DIVIDE", "Time Intelligence[Bad]") in ids


def test_ordinary_model_has_no_calc_items():
    # a normal table must not spuriously produce calculation items (determinism:
    # models without calc groups are unchanged).
    cat = parse_tmdl_model(
        "m", {"t.tmdl": "table Fact\n\tcolumn A\n\t\tdataType: int64\n\tmeasure 'F: M' = 1\n"}
    )
    assert cat.calculation_items == []
    assert [m.name for m in cat.measures] == ["F: M"]
