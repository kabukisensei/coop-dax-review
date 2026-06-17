"""Report renderers: JSON contract, Markdown + HTML grouping by model, determinism."""

from coop_dax_review.engine import Result
from coop_dax_review.finding import AgentReviewItem, Finding
from coop_dax_review.report import to_html, to_json, to_markdown

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
    assert payload["summary"] == {"error": 0, "warning": 1, "info": 1}
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
