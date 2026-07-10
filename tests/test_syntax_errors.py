"""Structural DAX syntax errors surface as SYNTAX_ERROR diagnostics.

Before this feature, malformed DAX (unbalanced parens/brackets, an unterminated
string/comment, an empty body) passed `check` with ZERO diagnostics while the
text rules half-analyzed the garbage. This mirrors coop-sql-review's syntax_error
work: the validator runs per measure + per calculated-column expression on
``blank_identifiers(mask_dax(dax))`` so parens/brackets inside identifiers /
strings / comments never miscount, it is error-severity by default (flipping
--strict / the verdict for free via issue #1), and it honors the rules.yml
`syntax_errors: error|warning|off` knob + an inline `coop-dax-review:ignore
syntax` directive.
"""

from __future__ import annotations

import json

from click.testing import CliRunner

from coop_dax_review.cli import cli
from coop_dax_review.diagnostics import SYNTAX_ERROR
from coop_dax_review.model import Column, Measure, ModelCatalog, Table
from coop_dax_review.parsers.syntax_validation import validate_dax_syntax


def _measure_catalog(name: str, dax: str, *, dax_line: int = 1, line: int = 1) -> ModelCatalog:
    cat = ModelCatalog(name="M", file="M.tmdl")
    cat.measures.append(Measure(name=name, dax=dax, file="M.tmdl", line=line, dax_line=dax_line))
    return cat


def _syntax(dax: str, *, name: str = "m", dax_line: int = 1, line: int = 1):
    return validate_dax_syntax([_measure_catalog(name, dax, dax_line=dax_line, line=line)])


# ---------------------------------------------------------------------------
# (1) the five structural checks each fire on simple DAX
# ---------------------------------------------------------------------------


def test_paren_depth_mismatch_fires():
    diags = _syntax("IF(X = 1, 1", name="Paren")
    assert len(diags) == 1
    assert diags[0].category == SYNTAX_ERROR
    assert diags[0].severity == "error"
    assert "paren" in diags[0].message.lower()
    assert "[Paren]" in diags[0].message


def test_extra_close_paren_fires():
    diags = _syntax("SUM(x))", name="Extra")
    assert len(diags) == 1
    assert "unexpected ')'" in diags[0].message


def test_bracket_depth_mismatch_fires():
    # A stray unmatched '[' (identifier brackets are masked; this one is bare).
    diags = _syntax("SUM(FactSales[Revenue) + [", name="Bracket")
    assert any("bracket" in d.message.lower() for d in diags)
    assert all(d.severity == "error" for d in diags)


def test_unterminated_string_literal_fires():
    diags = _syntax('"value without closing quote, 1, 2)', name="Str")
    assert any("unterminated string" in d.message for d in diags)
    assert all(d.severity == "error" for d in diags)


def test_unterminated_block_comment_fires():
    diags = _syntax("/* comment /* nested? DATESYTD([D])", name="Cmt")
    assert len(diags) == 1
    assert "unterminated block comment" in diags[0].message


def test_empty_measure_body_fires():
    diags = _syntax("   \n  \t ", name="Empty")
    assert len(diags) == 1
    assert diags[0].message == "[Empty]: empty measure body"


# ---------------------------------------------------------------------------
# precision: identifiers / strings never miscount
# ---------------------------------------------------------------------------


def test_identifiers_with_parens_do_not_miscount():
    # `[Net (USD)]` and a quoted table name with parens must NOT be counted — the
    # only real parens are CALCULATE(...)'s, which balance.
    diags = _syntax("CALCULATE([Net (USD)], 'Sales (2024)'[Amount])", name="Ids")
    assert diags == []


def test_strings_with_brackets_do_not_miscount():
    diags = _syntax('IF(x = "[brackets]", 1, 2)', name="StrBr")
    assert diags == []


def test_valid_multiline_var_return_is_clean():
    dax = "VAR a =\n    CALCULATE(\n        SUM(T[x]),\n        T[y] = 1\n    )\nRETURN\n    a"
    assert _syntax(dax, name="VR") == []


# ---------------------------------------------------------------------------
# line mapping
# ---------------------------------------------------------------------------


def test_syntax_error_line_points_correctly():
    # A paren mismatch on the 3rd line of the DAX body, whose first char sits on
    # file line 5, must be reported at absolute file line 7.
    dax = "SUM(\n  x\n  + IF(1, 1"  # the unclosed IF( is on the 3rd body line
    diags = _syntax(dax, name="LineMap", dax_line=5)
    assert diags, "an unclosed paren must be reported"
    lines = {d.line for d in diags}
    assert 7 in lines  # 5 (base) + 2 newlines to the unclosed '('


def test_syntax_error_message_contains_measure_name():
    diags = _syntax("SUM(x", name="Sales: Revenue")
    assert diags
    assert "[Sales: Revenue]" in diags[0].message


# ---------------------------------------------------------------------------
# (2) partial analysis survives — one broken measure never blinds a valid one
# ---------------------------------------------------------------------------


def test_partial_analysis_survives():
    cat = ModelCatalog(name="M", file="M.tmdl")
    cat.measures.append(Measure(name="Good", dax="SUM(T[x])", file="M.tmdl", line=1, dax_line=1))
    cat.measures.append(Measure(name="Broken", dax="IF(X = 1, 1", file="M.tmdl", line=5, dax_line=5))
    diags = validate_dax_syntax([cat])
    assert len(diags) == 1  # only the broken one
    assert "[Broken]" in diags[0].message
    assert diags[0].line == 5


# ---------------------------------------------------------------------------
# calculated columns are validated too
# ---------------------------------------------------------------------------


def test_calculated_column_expression_is_validated():
    cat = ModelCatalog(name="M", file="M.tmdl")
    tbl = Table(name="Fact", file="Fact.tmdl", line=1)
    tbl.columns.append(
        Column(name="Margin", is_calculated=True, expression="DIVIDE([Profit], [Revenue]", line=3)
    )
    tbl.columns.append(Column(name="PlainId", data_type="int64", line=2))  # not calculated -> skipped
    cat.tables.append(tbl)
    diags = validate_dax_syntax([cat])
    assert len(diags) == 1
    assert "Fact[Margin]" in diags[0].message
    assert diags[0].line == 3
    assert diags[0].file == "Fact.tmdl"


def test_plain_data_column_is_never_flagged():
    cat = ModelCatalog(name="M", file="M.tmdl")
    tbl = Table(name="Fact", file="Fact.tmdl", line=1)
    tbl.columns.append(Column(name="Revenue", data_type="double", line=2))
    cat.tables.append(tbl)
    assert validate_dax_syntax([cat]) == []


# ---------------------------------------------------------------------------
# end-to-end through the CLI: knob, suppression, strict, verdict
# ---------------------------------------------------------------------------


def _model_dir(tmp_path, measures: str) -> str:
    """Write a minimal one-table TMDL model whose FactSales table carries the
    given measure text, and return the model root for `check`."""
    root = tmp_path / "Model.SemanticModel" / "definition"
    (root / "tables").mkdir(parents=True)
    (root / "model.tmdl").write_text("model Model\n\tculture: en-US\n", encoding="utf-8")
    (root / "tables" / "FactSales.tmdl").write_text(
        "table FactSales\n\tcolumn Revenue\n\t\tdataType: double\n\n" + measures,
        encoding="utf-8",
    )
    return str(tmp_path / "Model.SemanticModel")


def _check_json(args):
    result = CliRunner().invoke(cli, ["check", *args, "--format", "json"])
    return result, json.loads(result.output)


# Two independent broken measures (each an unclosed paren) -> two syntax errors.
TWO_BROKEN = "\tmeasure 'A Bad' = IF([Revenue] = 1, 1\n\n\tmeasure 'B Bad' = SUM(FactSales[Revenue]\n"


def test_knob_error_mode_reports_two_errors(tmp_path):
    model = _model_dir(tmp_path, TWO_BROKEN)
    _result, payload = _check_json([model])
    diags = [d for d in payload["diagnostics"] if d["category"] == SYNTAX_ERROR]
    assert len(diags) == 2
    assert all(d["severity"] == "error" for d in diags)


def test_knob_warning_demotes_but_keeps_visible(tmp_path):
    model = _model_dir(tmp_path, TWO_BROKEN)
    cfg = tmp_path / "rules.yml"
    cfg.write_text("syntax_errors: warning\n", encoding="utf-8")
    _result, payload = _check_json([model, "--config", str(cfg)])
    diags = [d for d in payload["diagnostics"] if d["category"] == SYNTAX_ERROR]
    assert len(diags) == 2
    assert all(d["severity"] == "warning" for d in diags)  # visible, demoted


def test_knob_off_drops_them(tmp_path):
    model = _model_dir(tmp_path, TWO_BROKEN)
    cfg = tmp_path / "rules.yml"
    cfg.write_text("syntax_errors: off\n", encoding="utf-8")  # bare `off` -> YAML False
    _result, payload = _check_json([model, "--config", str(cfg)])
    assert not [d for d in payload["diagnostics"] if d["category"] == SYNTAX_ERROR]


def test_knob_missing_defaults_to_error(tmp_path):
    model = _model_dir(tmp_path, TWO_BROKEN)
    cfg = tmp_path / "rules.yml"
    cfg.write_text("rules:\n  DAX-USE-DIVIDE:\n    severity: warning\n", encoding="utf-8")
    _result, payload = _check_json([model, "--config", str(cfg)])
    diags = [d for d in payload["diagnostics"] if d["category"] == SYNTAX_ERROR]
    assert len(diags) == 2
    assert all(d["severity"] == "error" for d in diags)


def test_invalid_knob_value_is_a_friendly_usage_error(tmp_path):
    model = _model_dir(tmp_path, TWO_BROKEN)
    cfg = tmp_path / "rules.yml"
    cfg.write_text("syntax_errors: loud\n", encoding="utf-8")
    result = CliRunner().invoke(cli, ["check", model, "--config", str(cfg)])
    assert result.exit_code == 2
    assert "syntax_errors" in result.output
    assert "Traceback" not in result.output


def test_inline_ignore_syntax_silences_exactly_one(tmp_path):
    # An `ignore syntax` directive on the line ABOVE the second broken measure
    # silences only it, so exactly one syntax error remains.
    measures = (
        "\tmeasure 'A Bad' = IF([Revenue] = 1, 1\n\n"
        "\t// coop-dax-review:ignore syntax\n"
        "\tmeasure 'B Bad' = SUM(FactSales[Revenue]\n"
    )
    model = _model_dir(tmp_path, measures)
    _result, payload = _check_json([model])
    diags = [d for d in payload["diagnostics"] if d["category"] == SYNTAX_ERROR]
    assert len(diags) == 1
    assert "[A Bad]" in diags[0]["message"]  # only the un-ignored one


def test_inline_wildcard_ignore_silences_syntax(tmp_path):
    measures = "\t// coop-dax-review:ignore *\n\tmeasure 'A Bad' = IF([Revenue] = 1, 1\n"
    model = _model_dir(tmp_path, measures)
    _result, payload = _check_json([model])
    assert not [d for d in payload["diagnostics"] if d["category"] == SYNTAX_ERROR]


def test_rule_scoped_ignore_does_not_silence_syntax(tmp_path):
    # A rule-id ignore must NOT swallow a syntax error on the same line.
    measures = "\t// coop-dax-review:ignore DAX-USE-DIVIDE\n\tmeasure 'A Bad' = IF([Revenue] = 1, 1\n"
    model = _model_dir(tmp_path, measures)
    _result, payload = _check_json([model])
    assert [d for d in payload["diagnostics"] if d["category"] == SYNTAX_ERROR]


def test_strict_exits_two_on_a_syntax_error(tmp_path):
    model = _model_dir(tmp_path, "\tmeasure 'A Bad' = IF([Revenue] = 1, 1\n")
    strict = CliRunner().invoke(cli, ["check", model, "--strict"])
    assert strict.exit_code == 2
    advisory = CliRunner().invoke(cli, ["check", model])
    assert advisory.exit_code == 0  # default stays advisory


# A single broken measure (unclosed paren) whose only issue is the syntax error.
# Every measure trips the always-on best-practice rules (no formatString, an
# implicit measure name), so to isolate the DIAGNOSTIC axis of the strict gate /
# verdict from the FINDINGS axis, the noisy rules are disabled in these tests.
ONE_BROKEN = "\tmeasure 'A Bad' = SUM(FactSales[Revenue]\n"
_QUIET_RULES = (
    "rules:\n  DAX-FORMAT-STRING:\n    enabled: false\n  DAX-MEASURE-CATEGORY:\n    enabled: false\n"
    "  DAX-MEASURE-DESCRIPTION:\n    enabled: false\n"
)


def test_strict_passes_when_syntax_errors_are_downgraded(tmp_path):
    model = _model_dir(tmp_path, ONE_BROKEN)
    cfg = tmp_path / "rules.yml"
    cfg.write_text(_QUIET_RULES + "syntax_errors: warning\n", encoding="utf-8")
    downgraded = CliRunner().invoke(cli, ["check", model, "--config", str(cfg), "--strict"])
    assert downgraded.exit_code == 0  # no error-severity diagnostic, no findings
    err_cfg = tmp_path / "rules_err.yml"
    err_cfg.write_text(_QUIET_RULES, encoding="utf-8")  # default (error) knob
    strict = CliRunner().invoke(cli, ["check", model, "--config", str(err_cfg), "--strict"])
    assert strict.exit_code == 2


def test_verdict_not_clean_on_a_syntax_error(tmp_path):
    model = _model_dir(tmp_path, ONE_BROKEN)
    cfg = tmp_path / "rules.yml"
    cfg.write_text(_QUIET_RULES, encoding="utf-8")  # default (error) knob
    _result, payload = _check_json([model, "--config", str(cfg)])
    assert payload["findings"] == []  # rule findings disabled; only the syntax error
    assert payload["verdict"]["clean"] is False
    assert payload["verdict"]["highest_severity"] == "error"


def test_verdict_clean_when_syntax_errors_downgraded(tmp_path):
    # `warning` mode -> no error-severity diagnostic -> the verdict is clean again
    # (the noisy rules are disabled, isolating the diagnostic axis).
    model = _model_dir(tmp_path, ONE_BROKEN)
    cfg = tmp_path / "rules.yml"
    cfg.write_text(_QUIET_RULES + "syntax_errors: warning\n", encoding="utf-8")
    _result, payload = _check_json([model, "--config", str(cfg)])
    assert payload["findings"] == []
    assert payload["verdict"]["highest_severity"] != "error"
    assert payload["verdict"]["clean"] is True
