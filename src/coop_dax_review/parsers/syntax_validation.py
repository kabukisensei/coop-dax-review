"""Cheap STRUCTURAL DAX validation — parity with coop-sql-review's syntax_error.

This is drift DETECTION, not a DAX grammar. For every measure body and every
calculated-column expression it runs five structural checks and emits one
``SYNTAX_ERROR`` Diagnostic (severity ``error``) per problem found:

1. Unbalanced parentheses (depth goes < 0, or > 0 at the end).
2. Unbalanced brackets.
3. An unterminated string literal (``"...`` never closed before end-of-text).
4. An unterminated block comment (``/*`` never closed by ``*/``).
5. An empty body (nothing but whitespace after parsing).

Malformed DAX like this imports broken into Power BI and, before this pass, went
unreported while the text rules half-analyzed the garbage. Once a SYNTAX_ERROR is
error-severity it flips ``--strict``/the JSON verdict for free (issue #1).

PRECISION is the whole ballgame here: parens/brackets/quotes that live inside an
identifier (``[Net (USD)]``), a string literal, or a comment must never be
counted. So the paren/bracket balance is judged on
``blank_identifiers(mask_dax(dax))`` — strings, comments AND identifier contents
already blanked — and the unterminated-string / unterminated-comment checks read
the *raw* text with their own tiny state machine (mask_dax alone would have
already swallowed the unterminated run to EOF, hiding the very thing we flag).
The precision-guard tests run this over every fixture and the standards' own
example measures and assert ZERO diagnostics.
"""

from __future__ import annotations

from dataclasses import dataclass

from coop_dax_review.diagnostics import SYNTAX_ERROR, Diagnostic
from coop_dax_review.model import Column, Measure, ModelCatalog, Table
from coop_dax_review.parsers.dax import mask_dax
from coop_dax_review.rules.helpers import blank_identifiers


@dataclass(frozen=True)
class _Issue:
    """One structural problem, with a 0-based char offset into the DAX (for
    line mapping) and a human-readable description."""

    offset: int
    description: str


def _balance_issues(masked: str, open_ch: str, close_ch: str, noun: str) -> list[_Issue]:
    """Every unbalanced-``open_ch``/``close_ch`` problem in already-masked DAX.

    Reports the FIRST unmatched closer (depth would go negative) and, at the end,
    one issue per unmatched opener that was never closed — using each opener's own
    offset so the diagnostic points at the real culprit.
    """
    issues: list[_Issue] = []
    open_stack: list[int] = []
    for idx, ch in enumerate(masked):
        if ch == open_ch:
            open_stack.append(idx)
        elif ch == close_ch:
            if open_stack:
                open_stack.pop()
            else:
                issues.append(_Issue(idx, f"unbalanced {noun}: unexpected '{close_ch}'"))
    for idx in open_stack:
        issues.append(_Issue(idx, f"unbalanced {noun}: '{open_ch}' is never closed"))
    return issues


def _unterminated_issues(dax: str) -> list[_Issue]:
    """Unterminated string-literal and block-comment problems, scanned on the
    RAW DAX with a small state machine.

    Runs on the raw text (not ``mask_dax`` output) because masking now
    deliberately consumes an unterminated string/comment to EOF — so the leak we
    want to flag is invisible in the masked text. DAX escapes a quote by doubling
    it (``""``); a backslash is a literal char (no C-style escapes). String
    scanning wins over comment markers (a ``//`` / ``--`` / ``/*`` inside a
    string is not a comment), matching ``mask_dax``'s left-to-right precedence.
    """
    issues: list[_Issue] = []
    i, n = 0, len(dax)
    while i < n:
        ch = dax[i]
        if ch == '"':
            start = i
            i += 1
            closed = False
            while i < n:
                if dax[i] == '"':
                    if i + 1 < n and dax[i + 1] == '"':  # doubled-quote escape
                        i += 2
                        continue
                    closed = True
                    i += 1
                    break
                i += 1
            if not closed:
                issues.append(_Issue(start, "unterminated string literal (no closing '\"')"))
            continue
        if ch == "/" and i + 1 < n and dax[i + 1] == "*":
            start = i
            i += 2
            closed = False
            while i < n:
                if dax[i] == "*" and i + 1 < n and dax[i + 1] == "/":
                    closed = True
                    i += 2
                    break
                i += 1
            if not closed:
                issues.append(_Issue(start, "unterminated block comment (no closing '*/')"))
            continue
        if ch in "/-" and i + 1 < n and dax[i + 1] == ch:  # `//` or `--` line comment
            while i < n and dax[i] != "\n":
                i += 1
            continue
        i += 1
    return issues


def _structural_issues(dax: str) -> list[_Issue]:
    """Every structural problem in one DAX body/expression, in offset order.

    Parens and brackets are counted on ``blank_identifiers(mask_dax(dax))`` so a
    ``(`` inside ``[Net (USD)]`` or a ``"str"`` never miscounts; the
    unterminated-string / unterminated-comment scan reads the raw text.
    """
    masked = blank_identifiers(mask_dax(dax))
    issues: list[_Issue] = []
    issues.extend(_balance_issues(masked, "(", ")", "parentheses"))
    issues.extend(_balance_issues(masked, "[", "]", "brackets"))
    issues.extend(_unterminated_issues(dax))
    issues.sort(key=lambda issue: (issue.offset, issue.description))
    return issues


def _line_of(base_line: int, dax: str, offset: int) -> int:
    """The file line of ``offset`` within a DAX body whose first char sits on
    ``base_line`` (1-based). Interior newlines shift it down."""
    return base_line + dax[: max(0, offset)].count("\n")


def _validate_measure(measure: Measure, model_file: str) -> list[Diagnostic]:
    dax = measure.dax or ""
    base_line = measure.dax_line or measure.line or 0
    label = f"[{measure.name}]"
    diagnostics: list[Diagnostic] = []
    if not dax.strip():
        diagnostics.append(
            Diagnostic(
                severity="error",
                category=SYNTAX_ERROR,
                file=measure.file or model_file,
                line=base_line,
                message=f"{label}: empty measure body",
            )
        )
        return diagnostics
    for issue in _structural_issues(dax):
        diagnostics.append(
            Diagnostic(
                severity="error",
                category=SYNTAX_ERROR,
                file=measure.file or model_file,
                line=_line_of(base_line, dax, issue.offset),
                message=f"{label}: {issue.description}",
            )
        )
    return diagnostics


def _validate_column(column: Column, table: Table, model_file: str) -> list[Diagnostic]:
    # Only calculated columns carry a DAX expression to validate; a plain data
    # column has none (its `expression` stays empty), so it is skipped.
    if not column.is_calculated:
        return []
    dax = column.expression or ""
    base_line = column.line or table.line or 0
    label = f"{table.name}[{column.name}]"
    diagnostics: list[Diagnostic] = []
    if not dax.strip():
        diagnostics.append(
            Diagnostic(
                severity="error",
                category=SYNTAX_ERROR,
                file=table.file or model_file,
                line=base_line,
                message=f"{label}: empty calculated-column expression",
            )
        )
        return diagnostics
    for issue in _structural_issues(dax):
        diagnostics.append(
            Diagnostic(
                severity="error",
                category=SYNTAX_ERROR,
                file=table.file or model_file,
                line=_line_of(base_line, dax, issue.offset),
                message=f"{label}: {issue.description}",
            )
        )
    return diagnostics


def validate_dax_syntax(catalogs: list[ModelCatalog]) -> list[Diagnostic]:
    """Cheap structural DAX validation over every measure and calculated-column
    expression in every catalog. Returns one ``SYNTAX_ERROR`` Diagnostic per
    problem (severity ``error``); an empty list means everything is structurally
    sound. Order is deterministic (catalogs and their objects are already in a
    stable order; issues within a body are offset-sorted)."""
    diagnostics: list[Diagnostic] = []
    for catalog in catalogs:
        for measure in catalog.measures:
            diagnostics.extend(_validate_measure(measure, catalog.file))
        for table in catalog.tables:
            for column in table.columns:
                diagnostics.extend(_validate_column(column, table, catalog.file))
    return diagnostics
