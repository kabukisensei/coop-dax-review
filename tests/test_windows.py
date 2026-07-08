"""Windows-compat invariants (issue #4), carried from coop-data-doc's lessons:

- CRLF source must yield the same findings AND line numbers as LF (the parser
  normalizes line endings up front).
- The console report's own chrome is pure ASCII, so a legacy cp1252/cp437
  console never raises UnicodeEncodeError on it.
- JSON output is ``ensure_ascii`` — safe on any code page even when a message
  carries a non-ASCII character (the § marks in rule messages).
"""

from __future__ import annotations

from coop_dax_review.engine import Result, run_rules
from coop_dax_review.finding import AgentReviewItem, Finding
from coop_dax_review.parsers.tmdl import parse_tmdl_model
from coop_dax_review.report import console_lines, json_text

# A model whose only measure divides on line 6 (body under `measure X =`), so a
# finding's LINE — not just its presence — must survive CRLF normalization.
_MODEL_LF = (
    "table FactSales\n"
    "\tcolumn Amount\n"
    "\t\tdataType: double\n"
    "\n"
    "\tmeasure 'Sales: Ratio' =\n"
    "\t\t[Sales: A] / [Sales: B]\n"
)


def _findings(text: str):
    from coop_dax_review.rules import all_rules

    cat = parse_tmdl_model("M", {"tables/FactSales.tmdl": text})
    result = run_rules([cat], all_rules())
    return [(f.rule_id, f.object, f.line) for f in result.findings]


def test_crlf_findings_and_line_numbers_match_lf():
    lf = _findings(_MODEL_LF)
    crlf = _findings(_MODEL_LF.replace("\n", "\r\n"))
    assert lf == crlf
    # sanity: the corpus actually produced the divide finding on its real line.
    assert ("DAX-USE-DIVIDE", "[Sales: Ratio]", 6) in lf


def test_console_chrome_is_cp1252_safe():
    # Feed ASCII-content findings/agent items/diagnostics: the RENDERER's own
    # chrome (banner, badges, summary) must add no non-ASCII byte.
    result = Result(
        models_checked=1,
        findings=[
            Finding(
                rule_id="DAX-USE-DIVIDE",
                severity="warning",
                model="M",
                file="t.tmdl",
                line=6,
                object="[Sales: Ratio]",
                message="uses the / operator - prefer DIVIDE().",
                standard_ref="14",
            )
        ],
        agent_review=[
            AgentReviewItem(
                rule_id="DAX-STAR-SCHEMA",
                model="M",
                file="t.tmdl",
                object="DimThing",
                line=1,
                note="possible snowflake - judge whether to flatten.",
                standard_ref="6",
            )
        ],
    )
    text = "\n".join(console_lines(result, version="0.1.0"))
    text.encode("ascii")  # must not raise


def test_json_output_is_ascii_even_with_section_marks():
    # A real rule message carries "§"; ensure_ascii must escape it so the JSON
    # bytes are safe on a legacy console / code page.
    result = Result(
        models_checked=1,
        findings=[
            Finding(
                rule_id="DAX-USE-DIVIDE",
                severity="warning",
                model="M",
                file="t.tmdl",
                line=6,
                object="[Sales: Ratio]",
                message="uses the / operator — prefer DIVIDE() (§14).",
                standard_ref="§14",
            )
        ],
    )
    out = json_text(result, version="0.1.0", standards={"path": "p", "sha256": "s"})
    out.encode("ascii")  # must not raise
    assert "\\u00a7" in out  # the § is unicode-escaped, not raw
