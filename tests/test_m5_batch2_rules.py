"""Tests for M5 batch 2 (§17 hide FK, §18 summarizeBy, §19 display folders, §20 implicit)."""

from importlib import import_module

from coop_dax_review.model import Column, Measure, ModelCatalog, Relationship, Table
from coop_dax_review.rules.base import RuleContext


def _run(module, cat):
    mod = import_module(f"coop_dax_review.rules.{module}")
    ctx = RuleContext(mod.RULE, cat)
    return mod.detect(ctx) if mod.RULE.kind == "agent" else mod.check(ctx)


def _model(fact_cols, dim_cols=(("CustomerKey", "int64", True, "none"),)):
    """A Fact->DimCustomer model. Columns are (name, type, is_hidden, summarize_by)."""

    def cols(specs):
        return [Column(name=n, data_type=t, is_hidden=h, summarize_by=s, line=1) for (n, t, h, s) in specs]

    return ModelCatalog(
        name="M",
        tables=[
            Table(name="Fact", file="f.tmdl", columns=cols(fact_cols)),
            Table(name="DimCustomer", file="d.tmdl", columns=cols(dim_cols)),
        ],
        relationships=[
            Relationship(
                from_table="Fact", from_column="CustomerKey", to_table="DimCustomer", to_column="CustomerKey"
            )
        ],
    )


# -- DAX-HIDE-FK-COLUMNS (§17) -----------------------------------------------


def test_visible_fk_fires():
    cat = _model([("CustomerKey", "int64", False, "none"), ("Amount", "double", False, "sum")])
    findings = _run("dax_hide_fk_columns", cat)
    assert len(findings) == 1 and findings[0].object == "Fact[CustomerKey]"


def test_hidden_fk_silent():
    cat = _model([("CustomerKey", "int64", True, "none")])
    assert _run("dax_hide_fk_columns", cat) == []


# -- DAX-KEY-SUMMARIZEBY-NONE (§18) ------------------------------------------


def test_summing_numeric_key_fires():
    # A VISIBLE FK on the fact side auto-aggregates (summarizeBy != none).
    cat = _model([("CustomerKey", "int64", False, "sum")], dim_cols=(("CustomerKey", "int64", True, "none"),))
    findings = _run("dax_key_summarizeby_none", cat)
    assert len(findings) == 1 and findings[0].object == "Fact[CustomerKey]"


def test_key_with_none_silent():
    cat = _model([("CustomerKey", "int64", True, "none")])
    assert _run("dax_key_summarizeby_none", cat) == []


def test_hidden_summing_key_silent():
    # A hidden key can't be dragged onto a visual — the §18 drag-to-sum risk
    # doesn't exist; whether it SHOULD be hidden is §17's call.
    cat = _model([("CustomerKey", "int64", True, "sum")], dim_cols=(("CustomerKey", "int64", True, "none"),))
    assert _run("dax_key_summarizeby_none", cat) == []


def test_string_key_not_flagged():
    cat = _model([("CustomerKey", "string", True, "")], dim_cols=(("CustomerKey", "string", True, ""),))
    assert _run("dax_key_summarizeby_none", cat) == []


# -- DAX-DISPLAY-FOLDERS (§19) -----------------------------------------------


def test_many_measures_no_folders_fires():
    measures = [Measure(name=f"M{i}", dax="1", table="Fact") for i in range(6)]
    cat = ModelCatalog(name="M", tables=[Table(name="Fact", file="f.tmdl")], measures=measures)
    findings = _run("dax_display_folders", cat)
    assert len(findings) == 1 and findings[0].object == "Fact"


def test_few_measures_silent():
    measures = [Measure(name=f"M{i}", dax="1", table="Fact") for i in range(3)]
    cat = ModelCatalog(name="M", tables=[Table(name="Fact")], measures=measures)
    assert _run("dax_display_folders", cat) == []


def test_folders_in_use_silent():
    measures = [Measure(name=f"M{i}", dax="1", table="Fact", display_folder="Folder") for i in range(8)]
    cat = ModelCatalog(name="M", tables=[Table(name="Fact")], measures=measures)
    assert _run("dax_display_folders", cat) == []


def test_hidden_measures_excluded_from_folder_count():
    # issue #7: hidden measures aren't in the field list, so they don't count toward
    # the §19 threshold — 3 visible + 5 hidden must stay silent (only 3 visible).
    visible = [Measure(name=f"V{i}", dax="1", table="Fact") for i in range(3)]
    hidden = [Measure(name=f"H{i}", dax="1", table="Fact", is_hidden=True) for i in range(5)]
    cat = ModelCatalog(name="M", tables=[Table(name="Fact", file="f.tmdl")], measures=visible + hidden)
    assert _run("dax_display_folders", cat) == []


# -- DAX-IMPLICIT-MEASURE (§20, agent) ---------------------------------------


def test_visible_numeric_nonkey_emits_review():
    cat = _model([("CustomerKey", "int64", True, "none"), ("Amount", "double", False, "sum")])
    items = _run("dax_implicit_measure", cat)
    assert len(items) == 1 and items[0].object == "Fact[Amount]"


def test_hidden_or_none_or_key_silent():
    # hidden numeric, none-summarized numeric, and the (visible) key are all skipped.
    cat = _model(
        [
            ("CustomerKey", "int64", False, "sum"),  # a key -> §18's domain, skip here
            ("HiddenAmt", "double", True, "sum"),  # hidden
            ("NoAggAmt", "double", False, "none"),  # summarizeBy none
            ("Label", "string", False, "none"),  # non-numeric
        ]
    )
    assert _run("dax_implicit_measure", cat) == []


# -- hidden TABLES hide their columns and measures (§15/§17/§18/§19/§20) ------


def _hidden_table_model():
    """Fact -> Bridge where the whole Bridge (many-side) table is hidden; its
    visible key column would fire §17/§18 if the table's isHidden didn't count."""
    bridge = Table(
        name="Bridge",
        file="b.tmdl",
        is_hidden=True,
        columns=[Column(name="CustomerKey", data_type="int64", summarize_by="sum", line=1)],
    )
    dim = Table(
        name="DimCustomer",
        file="d.tmdl",
        columns=[Column(name="CustomerKey", data_type="int64", is_hidden=True, summarize_by="none", line=1)],
    )
    return ModelCatalog(
        name="M",
        tables=[bridge, dim],
        relationships=[
            Relationship(
                from_table="Bridge",
                from_column="CustomerKey",
                to_table="DimCustomer",
                to_column="CustomerKey",
            )
        ],
    )


def test_fk_on_hidden_table_not_flagged_by_hide_fk():
    # §17: hiding the table hides the FK from the field list — nothing to hide.
    assert _run("dax_hide_fk_columns", _hidden_table_model()) == []


def test_summing_key_on_hidden_table_not_flagged_by_summarizeby():
    # §18: a hidden table's key can't be dragged and summed.
    assert _run("dax_key_summarizeby_none", _hidden_table_model()) == []


def test_numeric_column_on_hidden_table_emits_no_implicit_measure_review():
    # §20: an auto-aggregating numeric column on a hidden table is invisible.
    cat = ModelCatalog(
        name="M",
        tables=[
            Table(
                name="Staging",
                file="s.tmdl",
                is_hidden=True,
                columns=[Column(name="Amount", data_type="double", summarize_by="sum", line=1)],
            )
        ],
    )
    assert _run("dax_implicit_measure", cat) == []


def test_measures_on_hidden_table_skipped_by_format_string_and_folders():
    # §15/§19: hiding a table removes its measures from the field list too.
    measures = [Measure(name=f"H: M{i}", dax="1", table="Staging") for i in range(8)]
    cat = ModelCatalog(
        name="M",
        tables=[Table(name="Staging", file="s.tmdl", is_hidden=True)],
        measures=measures,
    )
    assert _run("dax_format_string", cat) == []
    assert _run("dax_display_folders", cat) == []
