"""Report renderers: JSON contract, Markdown + HTML grouping by model, determinism."""

from coop_dax_review.engine import Result
from coop_dax_review.finding import AgentReviewItem, Finding
from coop_dax_review.report import console_lines, to_html, to_json, to_markdown

STANDARDS = {"path": "docs/standards.md", "sha256": "abc123"}


def _result() -> Result:
    # findings already in engine-sorted order (model, file, line, ...)
    return Result(
        findings=[
            Finding(
                "DAX-USE-DIVIDE",
                "warning",
                "Sales",
                "tables/FactSales.tmdl",
                12,
                "[Sales: Margin %]",
                "use DIVIDE() for safe division",
                "§14",
            ),
            Finding(
                "DAX-VAR-RETURN",
                "info",
                "Sales",
                "tables/FactSales.tmdl",
                30,
                "[Sales: Revenue YTD]",
                "consider VAR/RETURN for readability",
                "§3",
            ),
        ],
        agent_review=[
            AgentReviewItem(
                "DAX-CONTEXT-TRANSITION",
                "Sales",
                "tables/FactSales.tmdl",
                "[Sales: Total]",
                40,
                "CALCULATE inside an iterator",
                "§6",
            ),
        ],
        models_checked=1,
    )


def test_json_contract_keys():
    payload = to_json(_result(), version="0.1.0", standards=STANDARDS)
    assert payload["tool"] == "coop-dax-review"
    assert payload["schema_version"] == 3  # 3: the family identity rule (issue #14)
    assert payload["summary"] == {"error": 0, "warning": 1, "info": 1}
    assert set(payload["verdict"]) == {"clean", "highest_severity"}
    first = payload["findings"][0]
    assert set(first) == {
        "rule_id",
        "severity",
        "model",
        "file",
        "line",
        "object",
        "message",
        "standard_ref",
        "fingerprint",
    }


def test_markdown_groups_by_model_and_lists_findings():
    md = to_markdown(_result(), version="0.1.0", standards=STANDARDS)
    assert md.startswith("# coop-dax-review report")
    assert "- models checked: 1" in md
    assert "## Findings" in md
    assert "### `Sales`" in md
    assert "DAX-USE-DIVIDE" in md
    assert "[Sales: Margin %]" in md
    assert "## Agent review (judgment required)" in md


def test_html_is_self_contained_and_escapes():
    result = Result(
        findings=[Finding("R", "warning", "M", "f.tmdl", 1, "[o]", "x < y & z > w", "§9")],
        models_checked=1,
    )
    out = to_html(result, version="0.1.1", standards={"path": "p", "sha256": "s"})
    assert out.startswith("<!DOCTYPE html>")
    assert "<style>" in out  # inline CSS, no external/CDN assets
    assert "http://" not in out and "https://" not in out  # offline / self-contained
    # dynamic content is HTML-escaped (no raw <, >, & from the message)
    assert "x &lt; y &amp; z &gt; w" in out
    assert "x < y & z > w" not in out
    # branded: the Cooptimize logo is embedded inline as a data URI
    assert "data:image/png;base64," in out
    assert "DAX Review" in out


def test_html_groups_by_model_and_is_deterministic():
    a = to_html(_result(), version="0.1.0", standards=STANDARDS)
    b = to_html(_result(), version="0.1.0", standards=STANDARDS)
    assert a == b
    assert a.endswith("\n")
    assert ">Sales<" in a  # the model name heads its card
    assert "agent review" in a  # the agent-review pill is present


def test_html_empty_shows_no_issues():
    out = to_html(Result(models_checked=0), version="0.1.0", standards=STANDARDS)
    assert "No issues found." in out


def _multi_model_result() -> Result:
    # Out-of-order on purpose; the renderers must sort models. The "Zeta"
    # finding is model-level (line 0) so the location must render bare (no ":0").
    return Result(
        findings=[
            Finding(
                "DAX-MARKED-DATE-TABLE", "warning", "Zeta", "model.tmdl", 0, "Zeta", "mark a date table", "§8"
            ),
            Finding("DAX-USE-DIVIDE", "warning", "Alpha", "t.tmdl", 5, "[A: Margin]", "use DIVIDE()", "§14"),
        ],
        models_checked=2,
    )


def test_markdown_sorts_models_and_omits_zero_line():
    md = to_markdown(_multi_model_result(), version="0.1.0", standards=STANDARDS)
    assert md.index("### `Alpha`") < md.index("### `Zeta`")  # models sorted
    assert "`model.tmdl`" in md  # line 0 -> bare file path
    assert "model.tmdl:0" not in md


def test_html_sorts_models_and_omits_zero_line():
    out = to_html(_multi_model_result(), version="0.1.0", standards=STANDARDS)
    assert out.index(">Alpha<") < out.index(">Zeta<")  # model cards sorted
    assert "model.tmdl:0" not in out  # line 0 renders without the :0 suffix


def test_console_is_report_styled_and_plain_by_default():
    text = "\n".join(console_lines(_result(), version="0.2.0", standards=STANDARDS))
    assert "coop-dax-review" in text  # banner
    assert "DAX / model standards report" in text
    assert "===" in text  # banner / summary rules
    assert "SUMMARY" in text
    assert "1 warning" in text  # the fixture has 1 warning, 1 info
    assert "agent review" in text
    assert "Advisory only" in text
    assert "\033[" not in text  # no ANSI unless color is requested


def test_console_color_adds_ansi_only_when_requested():
    assert "\033[" in "\n".join(console_lines(_result(), color=True))
    assert "\033[" not in "\n".join(console_lines(_result(), color=False))


def test_console_chrome_is_ascii_safe_even_colored():
    # An empty result is pure chrome; it must be ASCII for a legacy Windows
    # console — and stay ASCII even colored (ANSI escape bytes are ASCII).
    assert "\n".join(console_lines(Result(models_checked=1))).isascii()
    assert "\n".join(console_lines(Result(models_checked=1), color=True)).isascii()
    assert "no issues found" in "\n".join(console_lines(Result(models_checked=1)))


def test_markdown_and_html_render_escaped_diagnostics():
    from coop_dax_review.diagnostics import Diagnostic

    result = Result(
        diagnostics=[Diagnostic("warning", "parse_failed", "m.tmdl", 0, "bad <x> & y")],
        models_checked=1,
    )
    md = to_markdown(result, version="0.1.0", standards=STANDARDS)
    assert "## Diagnostics (processing problems)" in md
    assert "bad <x> & y" in md  # markdown passes the message through as-authored

    out = to_html(result, version="0.1.0", standards=STANDARDS)
    assert "Diagnostics (processing problems)" in out
    assert "parse_failed" in out
    assert "bad &lt;x&gt; &amp; y" in out  # HTML-escaped
    assert "bad <x> & y" not in out


# ---- issue #15: per-rule count table in the SUMMARY (console + markdown + HTML)


def _multi_rule_result() -> Result:
    def f(rule, sev, obj):
        return Finding(rule, sev, "Sales", "t.tmdl", 1, obj, f"msg for {obj}", "§1")

    return Result(
        findings=[
            f("DAX-MEASURE-CATEGORY", "warning", "[A]"),
            f("DAX-MEASURE-CATEGORY", "warning", "[B]"),
            f("DAX-MEASURE-CATEGORY", "warning", "[C]"),
            f("DAX-VAR-RETURN", "info", "[D]"),
        ],
        models_checked=1,
    )


def test_console_summary_has_per_rule_counts_sorted_desc():
    text = "\n".join(console_lines(_multi_rule_result()))
    assert "Findings by rule" in text
    lines = text.splitlines()
    idx = next(i for i, line in enumerate(lines) if "Findings by rule" in line)
    table = [line for line in lines[idx + 1 :] if line.strip() and line.lstrip()[0].isdigit()]
    assert "3" in table[0] and "DAX-MEASURE-CATEGORY" in table[0]  # count desc
    assert "1" in table[1] and "DAX-VAR-RETURN" in table[1]
    assert "enabled: false" in text  # the closing rules.yml hint


def test_console_no_per_rule_table_when_clean():
    assert "Findings by rule" not in "\n".join(console_lines(Result(models_checked=1)))


def test_markdown_has_findings_by_rule_table():
    md = to_markdown(_multi_rule_result(), version="0.1.0", standards=STANDARDS)
    assert "## Findings by rule" in md
    assert "| 3 | warning | `DAX-MEASURE-CATEGORY` |" in md
    assert "| 1 | info | `DAX-VAR-RETURN` |" in md
    assert md.index("| 3 |") < md.index("| 1 |")  # sorted by count desc
    assert "enabled: false" in md


def test_html_has_findings_by_rule_table():
    out = to_html(_multi_rule_result(), version="0.1.0", standards=STANDARDS)
    assert "Findings by rule" in out
    assert '<table class="byrule">' in out
    assert '<td class="count">3</td>' in out
    assert "DAX-MEASURE-CATEGORY" in out
    assert "enabled: false" in out
    assert "http://" not in out and "https://" not in out  # still offline


# ---- issue #17: HTML severity/rule filters + locatable agent-review rows


def test_html_has_filter_bar_and_inline_script():
    out = to_html(_multi_rule_result(), version="0.1.0", standards=STANDARDS)
    assert 'class="filters"' in out
    assert 'data-sev="warning"' in out and 'data-rule="DAX-MEASURE-CATEGORY"' in out
    assert 'id="rulefilter"' in out
    assert '<option value="DAX-VAR-RETURN">' in out
    assert "<script>" in out  # small inline vanilla JS
    # still a self-contained offline single file: no CDN, no framework, no URLs
    assert "http://" not in out and "https://" not in out


def test_html_no_filter_bar_when_clean():
    out = to_html(Result(models_checked=1), version="0.1.0", standards=STANDARDS)
    assert 'class="filters"' not in out
    assert "<script>" not in out  # no dead script on a clean report


def test_html_agent_row_has_model_and_file_line():
    out = to_html(_result(), version="0.1.0", standards=STANDARDS)
    agent = out[out.index("Agent review") :]
    assert "Sales" in agent  # the model name
    assert "tables/FactSales.tmdl:40" in agent  # file:line
    assert "[Sales: Total]" in agent  # the object is still there


def test_html_model_level_agent_row_skips_redundant_object():
    result = Result(
        agent_review=[AgentReviewItem("DAX-VALIDATION", "Sales", "model.tmdl", "Sales", 0, "note", "§11")],
        models_checked=1,
    )
    out = to_html(result, version="0.1.0", standards=STANDARDS)
    agent = out[out.index("Agent review") :]
    # model shown once, not "Sales · Sales ·"
    assert agent.count("Sales &middot;") == 1


def test_console_agent_row_has_model_and_file_line():
    text = "\n".join(console_lines(_result()))
    agent = text[text.index("Agent review") :]
    assert "Sales - tables/FactSales.tmdl:40" in agent
