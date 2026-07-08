"""Regression tests for the second adversarial review's confirmed findings.

Each test group carries the finding id it guards, so a failure points back to
the exact reviewed bug.
"""

import codecs
import json
from importlib import import_module
from pathlib import Path

import pytest
from click.testing import CliRunner

from coop_dax_review.cli import build_catalogs, cli, discover_inputs
from coop_dax_review.parsers.bim import parse_bim_model
from coop_dax_review.parsers.tmdl import group_tmdl_files, model_root, parse_tmdl_model
from coop_dax_review.rules import all_rules
from coop_dax_review.rules.base import RuleContext

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _run_rule(rule_module, catalog):
    mod = import_module(rule_module)
    ctx = RuleContext(mod.RULE, catalog)
    return mod.check(ctx)


def _check_json(*args):
    result = CliRunner().invoke(cli, ["check", *args, "--format", "json"])
    assert result.exit_code == 0
    return json.loads(result.stdout)  # stdout only: stderr hints never pollute the contract


# -- tmdl-measure-dax-truncated-by-header-comment ------------------------------
#
# The standards' OWN §12 header (`/* Measure: ... Purpose: ... */`) must not
# truncate the measure body: `Purpose:` matches the generic `Word:` property
# shape but is comment text, not a TMDL property.

SECTION12_TMDL = """table FactSales
\tcolumn Revenue
\t\tdataType: double

\tmeasure 'Sales: Revenue YTD' =
\t\t/*
\t\t  Measure: [Sales: Revenue YTD]
\t\t  Purpose: Year-to-date revenue across all sales transactions
\t\t  Context: Works in any filter context
\t\t  Dependencies: FactSales[Revenue], DimDate[Date]
\t\t  Author: Aaron Jennings
\t\t  Date: 2026-06-01
\t\t*/
\t\tVAR Result =
\t\t\tSUMX(FactSales, FactSales[Revenue])
\t\tRETURN
\t\t\tResult
\t\tformatString: #,0.00
"""


def test_section12_header_comment_does_not_truncate_measure_dax():
    cat = parse_tmdl_model("Sales", {"tables/FactSales.tmdl": SECTION12_TMDL})
    (measure,) = cat.measures
    assert "SUMX" in measure.dax
    assert "RETURN" in measure.dax
    assert measure.dax.rstrip().endswith("Result")  # the full body, not just "/*"
    assert measure.format_string == "#,0.00"  # the real property still terminates the body


def test_arbitrary_word_colon_line_no_longer_terminates_dax():
    # A bare `Word:` line (no comment marker — e.g. a sloppily unwrapped
    # header continuation) is not a TMDL measure property either — only the
    # finite real property set ends the body. The old generic `^Word\s*:`
    # terminator truncated the body at `Purpose:` here.
    tmdl = "table T\n\tmeasure 'S: M' =\n\t\tPurpose: legacy note\n\t\tSUM(T[A])\n"
    cat = parse_tmdl_model("M", {"t.tmdl": tmdl})
    (measure,) = cat.measures
    assert "SUM(T[A])" in measure.dax


def test_real_tmdl_properties_still_terminate_dax():
    tmdl = "table T\n\tmeasure 'S: M' =\n\t\tSUM(T[A])\n\t\tlineageTag: 1234-abcd\n\t\tdisplayFolder: KPIs\n"
    cat = parse_tmdl_model("M", {"t.tmdl": tmdl})
    (measure,) = cat.measures
    assert measure.dax == "SUM(T[A])"
    assert "lineageTag" not in measure.dax
    assert measure.display_folder == "KPIs"


# -- model-grouping-by-bare-name / tmdl-group-by-name-merges-distinct-models ---


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def test_same_named_models_in_different_folders_stay_distinct(tmp_path):
    for env, table in (("dev", "FactA"), ("prod", "FactB")):
        _write(
            tmp_path / env / "Sales.SemanticModel" / "definition" / "tables" / "T.tmdl",
            f"table {table}\n\tcolumn A\n\t\tdataType: double\n",
        )
    tmdl, bim = discover_inputs((str(tmp_path),))
    catalogs = build_catalogs(tmdl, bim)
    assert len(catalogs) == 2  # NOT merged into one chimera model
    assert [c.name for c in catalogs] == ["Sales", "Sales"]  # display name kept
    assert sorted(t.name for c in catalogs for t in c.tables) == ["FactA", "FactB"]
    assert all(len(c.tables) == 1 for c in catalogs)


# -- tmdl-flat-folder-splits-model-per-file -------------------------------------


def test_flat_folder_of_tmdl_files_forms_one_model(tmp_path):
    d = tmp_path / "MyModel"
    _write(d / "FactSales.tmdl", "table FactSales\n\tcolumn ProductId\n\t\tdataType: int64\n")
    _write(d / "DimProduct.tmdl", "table DimProduct\n\tcolumn ProductId\n\t\tdataType: int64\n")
    _write(
        d / "relationships.tmdl",
        "relationship r1\n\tfromColumn: FactSales.ProductId\n\ttoColumn: DimProduct.ProductId\n",
    )
    tmdl, bim = discover_inputs((str(d),))
    catalogs = build_catalogs(tmdl, bim)
    assert len(catalogs) == 1  # one model, not one per file
    cat = catalogs[0]
    assert cat.name == "MyModel"  # named after the folder
    assert {t.name for t in cat.tables} == {"DimProduct", "FactSales"}
    assert len(cat.relationships) == 1  # relationships joined the same catalog


def test_flat_folder_models_checked_is_one_end_to_end(tmp_path):
    d = tmp_path / "MyModel"
    _write(d / "FactSales.tmdl", "table FactSales\n\tcolumn ProductId\n\t\tdataType: int64\n")
    _write(d / "DimProduct.tmdl", "table DimProduct\n\tcolumn ProductId\n\t\tdataType: int64\n")
    payload = _check_json(str(d))
    assert payload["models_checked"] == 1


def test_model_root_fallback_groups_by_parent_directory():
    root, name = model_root("mymodel/FactSales.tmdl")
    assert (root, name) == ("mymodel", "mymodel")


# -- rules-yml-load-crash -------------------------------------------------------
#
# Contract (mirrors the coop-sql-review twin): a malformed / mis-encoded /
# invalid rules.yml is a friendly one-line usage error (exit 2) naming the
# file — never a traceback.

_BAD_RULES_YML = [
    b"rules: [unclosed\n",  # invalid YAML
    b"rules:\n  - DAX-USE-DIVIDE\n",  # non-dict `rules:` section
    b"- just\n- a\n- list\n",  # non-dict top level
    b"rules:\n  DAX-USE-DIVIDE:\n    severity: fatal\n",  # invalid severity
    b"note: caf\xe9\n",  # cp1252 bytes — not UTF-8
]


@pytest.mark.parametrize("content", _BAD_RULES_YML)
def test_bad_rules_yml_yields_friendly_one_line_error(tmp_path, content):
    cfg = tmp_path / "rules.yml"
    cfg.write_bytes(content)
    result = CliRunner().invoke(cli, ["check", str(FIXTURES), "--config", str(cfg)])
    assert result.exit_code == 2  # a friendly usage error, not a crash
    assert "could not load config" in result.stderr
    assert "Traceback" not in result.output + result.stderr


def test_utf16_rules_yml_names_the_encoding(tmp_path):
    # PowerShell 5's `>` writes UTF-16; the error must say how to fix it.
    cfg = tmp_path / "rules.yml"
    cfg.write_bytes("rules: {}\n".encode("utf-16"))
    result = CliRunner().invoke(cli, ["check", str(FIXTURES), "--config", str(cfg)])
    assert result.exit_code == 2
    assert "could not load config" in result.stderr and "UTF-8" in result.stderr


def test_bad_cwd_rules_yml_is_friendly_too(tmp_path, monkeypatch):
    # The auto-discovered ./rules.yml must get the same friendly wrap.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "rules.yml").write_bytes(b"rules: [unclosed\n")
    result = CliRunner().invoke(cli, ["check", str(FIXTURES)])
    assert result.exit_code == 2
    assert "could not load config" in result.stderr
    assert "Traceback" not in result.output + result.stderr


def test_missing_explicit_config_is_rejected_as_typo(tmp_path):
    # An explicit --config that doesn't exist would silently drop the team's
    # overrides; auto-discovery absence stays silent (empty config).
    result = CliRunner().invoke(cli, ["check", str(FIXTURES), "--config", str(tmp_path / "nope.yml")])
    assert result.exit_code == 2
    assert "config file not found" in result.stderr


# -- empty-discovery-emits-no-json ----------------------------------------------


def test_empty_discovery_still_emits_json_contract(tmp_path):
    result = CliRunner().invoke(cli, ["check", str(tmp_path), "--format", "json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)  # valid JSON even with nothing scanned
    assert payload["models_checked"] == 0
    assert payload["findings"] == []
    assert any(d["category"] == "scan_empty" for d in payload["diagnostics"])
    assert "No TMDL" in result.stderr  # the human hint stays


def test_typoed_path_yields_scan_empty_diagnostic(tmp_path):
    payload = _check_json(str(tmp_path / "typo"))
    diags = [d for d in payload["diagnostics"] if d["category"] == "scan_empty"]
    assert len(diags) == 1
    assert "path not found" in diags[0]["message"]


def test_strict_fails_on_zero_models(tmp_path):
    assert CliRunner().invoke(cli, ["check", str(tmp_path), "--strict"]).exit_code == 2
    # a typo'd path with --strict must not pass vacuously
    assert CliRunner().invoke(cli, ["check", str(tmp_path / "typo"), "--strict"]).exit_code == 2


def test_empty_discovery_still_writes_extra_sinks_and_log(tmp_path):
    md = tmp_path / "r.md"
    log = tmp_path / "diag.log"
    result = CliRunner().invoke(
        cli, ["check", str(tmp_path / "empty"), "--md", str(md), "--log-file", str(log)]
    )
    assert result.exit_code == 0
    assert md.is_file() and "models checked: 0" in md.read_text(encoding="utf-8")
    assert log.is_file()


# -- utf16-tmdl-silent-clean ------------------------------------------------------

_UTF16_BODY = "table T\n\tcolumn A\n\t\tdataType: double\n\n\tmeasure 'M: R' = T[A] / 2\n"


@pytest.mark.parametrize(
    "data",
    [
        _UTF16_BODY.encode("utf-16"),  # LE with BOM (PowerShell 5 redirect style)
        codecs.BOM_UTF16_BE + _UTF16_BODY.encode("utf-16-be"),
    ],
    ids=["utf-16-le-bom", "utf-16-be-bom"],
)
def test_utf16_tmdl_model_is_actually_parsed_not_silently_clean(tmp_path, data):
    target = tmp_path / "U.SemanticModel" / "definition" / "tables" / "T.tmdl"
    target.parent.mkdir(parents=True)
    target.write_bytes(data)
    payload = _check_json(str(tmp_path))
    assert any(f["rule_id"] == "DAX-USE-DIVIDE" for f in payload["findings"])  # it parsed
    assert payload["verdict"]["clean"] is False


def _write_undecodable_model(tmp_path):
    target = tmp_path / "B.SemanticModel" / "definition" / "tables" / "junk.tmdl"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"table T\n\x93\x00\xffgarbage")  # not UTF-8, no UTF-16 BOM
    return target


def test_undecodable_tmdl_is_error_severity_file_unreadable(tmp_path):
    # issue #1: an undecodable file contributed NOTHING to the catalog — it is an
    # error-severity file_unreadable (not a parse_failed warning), so a model whose
    # only file is mojibake can't pass --strict / verdict as clean.
    _write_undecodable_model(tmp_path)
    payload = _check_json(str(tmp_path))  # non-strict -> still exit 0 (happy path unchanged)
    diags = [d for d in payload["diagnostics"] if d["category"] == "file_unreadable"]
    assert diags and any("junk.tmdl" in d["file"] for d in diags)
    assert all(d["severity"] == "error" for d in diags)
    assert payload["findings"] == []  # nothing invented from mojibake
    # the error diagnostic makes the verdict NOT clean even with zero findings
    assert payload["verdict"]["clean"] is False
    assert payload["verdict"]["highest_severity"] == "error"


def test_strict_exits_two_on_error_severity_diagnostic(tmp_path):
    # issue #1: --strict must fail (exit 2) when an error-severity diagnostic remains,
    # even with zero findings — an unreadable model must not pass CI as clean.
    _write_undecodable_model(tmp_path)
    strict = CliRunner().invoke(cli, ["check", str(tmp_path), "--strict", "--format", "json"])
    assert strict.exit_code == 2
    # ...but without --strict the tool stays advisory (exit 0).
    lenient = CliRunner().invoke(cli, ["check", str(tmp_path), "--format", "json"])
    assert lenient.exit_code == 0


def test_strict_stays_zero_on_a_clean_model(tmp_path):
    # happy path unchanged: zero findings + zero diagnostics still exits 0 under --strict.
    _write(
        tmp_path / "Clean.SemanticModel" / "definition" / "tables" / "T.tmdl",
        "table T\n\tcolumn A\n\t\tdataType: int64\n\t\tsummarizeBy: none\n",
    )
    ok = CliRunner().invoke(cli, ["check", str(tmp_path), "--strict", "--format", "json"])
    assert ok.exit_code == 0
    assert json.loads(ok.stdout)["verdict"]["clean"] is True


# -- dax-bim-double-count-overlapping-roots ---------------------------------------


def test_overlapping_roots_check_each_file_once(tmp_path, monkeypatch):
    bim = tmp_path / "model.bim"
    bim.write_text(
        json.dumps(
            {
                "name": "M",
                "model": {
                    "tables": [
                        {
                            "name": "T",
                            "columns": [{"name": "A", "dataType": "double"}],
                            "measures": [{"name": "Revenue", "expression": "1"}],
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    tmdl, bims = discover_inputs((".", str(tmp_path)))
    assert len(bims) == 1  # deduped by resolved path (mirrors coop-sql-review aecbe61)
    payload = _check_json(".", str(tmp_path))
    assert payload["models_checked"] == 1
    fingerprints = [f["fingerprint"] for f in payload["findings"]]
    assert len(fingerprints) == len(set(fingerprints))  # no duplicated findings


def test_overlapping_roots_dedupe_tmdl_too(tmp_path, monkeypatch):
    _write(
        tmp_path / "Sales.SemanticModel" / "definition" / "tables" / "T.tmdl",
        "table T\n\tcolumn A\n\t\tdataType: double\n",
    )
    monkeypatch.chdir(tmp_path)
    tmdl, bims = discover_inputs((".", str(tmp_path)))
    assert len(tmdl) == 1


# -- explicit-file-misclassified-as-bim / any-non-tmdl-file-treated-as-bim ---------


def test_explicit_non_model_file_is_not_parsed_as_bim(tmp_path):
    notes = tmp_path / "notes.txt"
    notes.write_text("hello\n", encoding="utf-8")
    tmdl, bim = discover_inputs((str(notes),))
    assert (tmdl, bim) == ([], [])  # neither bucket
    result = CliRunner().invoke(cli, ["check", str(notes), "--format", "json"])
    assert result.exit_code == 0
    assert "not a TMDL (.tmdl) or .bim model file" in result.stderr
    payload = json.loads(result.stdout)
    assert payload["models_checked"] == 0  # no phantom model
    assert not any("could not parse .bim" in d["message"] for d in payload["diagnostics"])


def test_explicit_bim_and_tmdl_files_still_accepted():
    tmdl, bim = discover_inputs((str(FIXTURES / "legacy.bim"),))
    assert [p.name for p in bim] == ["legacy.bim"] and tmdl == []


# -- parse-crash-degrades-whole-model-and-misattributes-file -----------------------


def test_unparseable_table_header_degrades_only_that_file():
    # "table =" matches the table-header shape but has no extractable name; it
    # must not raise, and the healthy file must still be parsed.
    cat = parse_tmdl_model("Bad", {"a_fine.tmdl": "table T\n\tcolumn X\n", "z_weird.tmdl": "table =\n"})
    assert [t.name for t in cat.tables] == ["T"]
    (diag,) = cat.diagnostics
    assert diag.category == "parse_failed"
    assert diag.file == "z_weird.tmdl"  # the OFFENDING file, not the alphabetically-first
    assert diag.line == 1


def test_unparseable_table_block_is_skipped_and_next_table_parsed():
    text = "table =\n\tcolumn Y\n\ntable Good\n\tcolumn Z\n"
    cat = parse_tmdl_model("M", {"t.tmdl": text})
    assert [t.name for t in cat.tables] == ["Good"]
    assert len(cat.diagnostics) == 1


def test_unparseable_table_header_e2e_other_files_still_checked(tmp_path):
    root = tmp_path / "X.SemanticModel" / "definition" / "tables"
    _write(root / "good.tmdl", "table T\n\tmeasure 'S: R' = T[A] / 2\n")
    _write(root / "weird.tmdl", "table =\n")
    payload = _check_json(str(tmp_path))
    assert any(f["rule_id"] == "DAX-USE-DIVIDE" for f in payload["findings"])  # still checked
    diags = [d for d in payload["diagnostics"] if d["category"] == "parse_failed"]
    assert diags and all("weird.tmdl" in d["file"] for d in diags)


# -- quoted-table-identifiers-never-masked ------------------------------------------


def test_slash_in_quoted_table_name_does_not_fire_use_divide(make_catalog):
    cat = make_catalog(measures=[("Plan: Total", "SUMX('Actual/Budget', [Amt])")])
    assert _run_rule("coop_dax_review.rules.dax_use_divide", cat) == []


def test_real_division_next_to_quoted_name_still_fires(make_catalog):
    cat = make_catalog(measures=[("Plan: Ratio", "SUMX('Actual/Budget', [Amt]) / 2")])
    assert len(_run_rule("coop_dax_review.rules.dax_use_divide", cat)) == 1


def test_parens_in_quoted_table_name_not_counted_as_calls(make_catalog):
    # 2 real calls (threshold 3) — the "Sales (" inside each quoted name must not count.
    cat = make_catalog(measures=[("Sales: Two Sums", "SUM('Sales (2024)'[Amt]) + SUM('Sales (2024)'[Qty])")])
    assert _run_rule("coop_dax_review.rules.dax_var_return", cat) == []


def test_paren_in_quoted_name_does_not_flag_sibling_calculate(make_catalog):
    # The unbalanced "(" inside the quoted name must not keep the first CALCULATE
    # open on the paren stack and flag the independent sibling as nested.
    cat = make_catalog(measures=[("M", "CALCULATE(SUM('A (x'[V])) + CALCULATE([Other])")])
    assert _run_rule("coop_dax_review.rules.dax_no_nested_calculate", cat) == []


def test_var_keyword_inside_quoted_table_name_is_not_var_return(make_catalog):
    # 'Var Data' must not read as a VAR keyword and suppress the finding.
    cat = make_catalog(measures=[("S: M", "SUMX('Var Data', [A]) + SUMX('Return Data', [B]) + SUM(T[C])")])
    assert len(_run_rule("coop_dax_review.rules.dax_var_return", cat)) == 1


# -- registry-silently-drops-rules-and-count-unpinned --------------------------------


def test_registry_advertises_exactly_25_rules():
    # Bump this pin in the same commit that adds/removes a rule. 25 as of issue #10
    # (added DAX-AUTO-DATETIME §21).
    rules = all_rules()
    assert len(rules) == 25
    assert len({r.id for r in rules}) == 25  # ids unique


def test_every_dax_module_contributes_exactly_one_rule():
    import pkgutil

    import coop_dax_review.rules as pkg

    modules = [m.name for m in pkgutil.iter_modules(pkg.__path__) if m.name.startswith("dax_")]
    assert len(modules) == len(all_rules())


def test_registry_raises_loudly_on_misdeclared_rule_module(monkeypatch):
    import coop_dax_review.rules.dax_use_divide as mod

    monkeypatch.setattr(mod, "RULE", object())
    with pytest.raises(TypeError, match="dax_use_divide"):
        all_rules()


# -- dax-upgrade-check-flag-dropped ----------------------------------------------------


def _fake_plan(monkeypatch):
    from coop_dax_review import upgrade as upmod

    plan = upmod.UpgradePlan(
        package_name="coop-dax-review",
        install_method="pipx",
        checkout=None,
        tool_installed="0.1.0",
        tool_note="already on the latest release (0.1.0)",
    )
    monkeypatch.setattr(upmod, "build_plan", lambda *a, **k: plan)


def test_upgrade_check_reports_status_only(monkeypatch):
    # SQL-twin parity: --check reports freshness and stops before the command.
    _fake_plan(monkeypatch)
    result = CliRunner().invoke(cli, ["upgrade", "--check"])
    assert result.exit_code == 0
    assert "coop-dax-review 0.1.0" in result.output
    assert "does not update itself" not in result.output  # no upgrade command printed
    assert "pipx upgrade" not in result.output


def test_update_alias_supports_check_too(monkeypatch):
    _fake_plan(monkeypatch)
    assert CliRunner().invoke(cli, ["update", "--check"]).exit_code == 0


# -- dax-missing-parse-progress-bar -----------------------------------------------------


def test_build_catalogs_ticks_once_per_model_file():
    tmdl, bim = discover_inputs((str(FIXTURES),))
    ticks: list = []
    build_catalogs(tmdl, bim, on_file=lambda *a: ticks.append(a))
    assert len(ticks) == len(tmdl) + len(bim)


def test_check_wires_the_core_parse_progress_bar(monkeypatch):
    from coop_dax_review.progress import Progress

    seen = {}
    real_bar = Progress.bar

    def spy(self, label, total):
        seen["bar"] = (label, total)
        return real_bar(self, label, total)

    monkeypatch.setattr(Progress, "bar", spy)
    result = CliRunner().invoke(cli, ["check", str(FIXTURES)])
    assert result.exit_code == 0
    assert seen["bar"] == ("Parsing", 4)  # 3 .tmdl + 1 .bim in the fixtures


# -- inline-suppression-no-e2e-test (coverage) -------------------------------------------

_DIVIDE_MODEL = "table T\n\tcolumn A\n\t\tdataType: double\n\n\tmeasure 'M: Ratio' = T[A] / 2\n"


def _model_with(tmp_path, table_text):
    _write(tmp_path / "S.SemanticModel" / "definition" / "tables" / "T.tmdl", table_text)
    return str(tmp_path)


def test_inline_ignore_control_fires_without_directive(tmp_path):
    payload = _check_json(_model_with(tmp_path, _DIVIDE_MODEL))
    assert any(f["rule_id"] == "DAX-USE-DIVIDE" for f in payload["findings"])


def test_inline_ignore_same_line_suppresses_finding_e2e(tmp_path):
    text = _DIVIDE_MODEL.replace("/ 2\n", "/ 2  // coop-dax-review:ignore DAX-USE-DIVIDE\n")
    payload = _check_json(_model_with(tmp_path, text))
    assert not any(f["rule_id"] == "DAX-USE-DIVIDE" for f in payload["findings"])
    # only the targeted rule is gone; others still report
    assert any(f["rule_id"] == "DAX-FORMAT-STRING" for f in payload["findings"])


def test_inline_ignore_line_above_suppresses_finding_e2e(tmp_path):
    text = _DIVIDE_MODEL.replace(
        "\tmeasure 'M: Ratio'",
        "\t// coop-dax-review:ignore DAX-USE-DIVIDE\n\tmeasure 'M: Ratio'",
    )
    payload = _check_json(_model_with(tmp_path, text))
    assert not any(f["rule_id"] == "DAX-USE-DIVIDE" for f in payload["findings"])
    assert any(f["rule_id"] == "DAX-FORMAT-STRING" for f in payload["findings"])


# -- parser-formatstring-displayfolder-seam-untested (coverage) ----------------------------


def test_tmdl_parser_extracts_formatstring_and_displayfolder():
    tmdl = (
        "table T\n"
        "\tmeasure 'S: M' = SUM(T[A])\n"
        "\t\tformatString: #,0.00\n"
        "\t\tdisplayFolder: KPIs\\Revenue\n"
        "\tmeasure 'S: Dyn' = 1\n"
        "\t\tformatStringDefinition =\n"
        '\t\t\tSELECTEDVALUE(Fmt[Str], "#,0")\n'
        "\tmeasure 'S: None' = 2\n"
    )
    cat = parse_tmdl_model("M", {"t.tmdl": tmdl})
    by = {m.name: m for m in cat.measures}
    assert by["S: M"].format_string == "#,0.00"
    assert by["S: M"].display_folder == "KPIs\\Revenue"
    assert by["S: M"].dax == "SUM(T[A])"  # properties are not part of the DAX
    assert by["S: Dyn"].format_string == "<dynamic>"  # formatStringDefinition marker
    assert "SELECTEDVALUE" not in by["S: Dyn"].dax
    assert by["S: None"].format_string == ""
    assert by["S: None"].display_folder == ""


def test_bim_parser_extracts_formatstring_and_displayfolder():
    bim = json.dumps(
        {
            "name": "M",
            "model": {
                "tables": [
                    {
                        "name": "T",
                        "columns": [{"name": "A"}],
                        "measures": [
                            {
                                "name": "B: M",
                                "expression": "1",
                                "formatString": "0.0%",
                                "displayFolder": "KPIs",
                            },
                            {
                                "name": "B: Dyn",
                                "expression": "1",
                                "formatStringDefinition": {"expression": "SELECTEDVALUE(F[S])"},
                            },
                            {"name": "B: None", "expression": "1"},
                        ],
                    }
                ]
            },
        }
    )
    cat = parse_bim_model("m.bim", bim)
    by = {m.name: m for m in cat.measures}
    assert by["B: M"].format_string == "0.0%"
    assert by["B: M"].display_folder == "KPIs"
    assert by["B: Dyn"].format_string == "<dynamic>"
    assert by["B: None"].format_string == ""
    assert by["B: None"].display_folder == ""


# -- no-crlf-bom-fixtures-windows-first (coverage) ------------------------------------------


def _findings_key(payload):
    return [(f["rule_id"], f["object"], f["line"]) for f in payload["findings"]]


@pytest.mark.parametrize("bom", [False, True], ids=["crlf", "bom+crlf"])
def test_crlf_and_bom_model_parses_identically_to_lf(tmp_path, bom):
    src = FIXTURES / "Sales.SemanticModel"
    baseline = _check_json(str(src))
    dst = tmp_path / "Sales.SemanticModel"
    for f in sorted(src.rglob("*.tmdl")):
        target = dst / f.relative_to(src)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = f.read_text(encoding="utf-8").replace("\n", "\r\n").encode("utf-8")
        if bom:
            data = codecs.BOM_UTF8 + data
        target.write_bytes(data)
    got = _check_json(str(dst))
    assert got["models_checked"] == baseline["models_checked"] == 1
    assert _findings_key(got) == _findings_key(baseline)  # same rules, objects AND lines
    assert got["summary"] == baseline["summary"]


# -- group_tmdl_files invariants after the re-keying ----------------------------------------


def test_group_tmdl_files_keys_by_model_root_directory(tmp_path):
    a = tmp_path / "dev" / "Sales.SemanticModel" / "definition" / "t.tmdl"
    b = tmp_path / "prod" / "Sales.SemanticModel" / "definition" / "t.tmdl"
    _write(a, "table A\n")
    _write(b, "table B\n")
    display = {
        a: "dev/Sales.SemanticModel/definition/t.tmdl",
        b: "prod/Sales.SemanticModel/definition/t.tmdl",
    }
    groups, unreadable = group_tmdl_files([a, b], display)
    assert unreadable == []
    assert len(groups) == 2  # distinct roots -> distinct models, same display name
    assert sorted(name for _root, name in groups) == ["Sales", "Sales"]
