"""DAX masking + reference extraction: the foundation every text rule relies on."""

from coop_dax_review.parsers.dax import bracket_refs, mask_dax


def test_mask_blanks_comments_and_strings_preserving_offsets():
    dax = 'SUM(x) -- CALCULATE here\n/* CALCULATE */ "CALCULATE"'
    masked = mask_dax(dax)
    assert len(masked) == len(dax)  # offsets preserved
    assert masked.count("\n") == dax.count("\n")  # newlines preserved
    assert "CALCULATE" not in masked  # keyword inside comment/string is gone
    assert masked.startswith("SUM(x)")


def test_bracket_refs_distinguishes_qualified_from_bare():
    refs = bracket_refs(mask_dax("CALCULATE([Total Rev], FactSales[Revenue], 'Dim Date'[Date])"))
    by_name = {r.name: r for r in refs}
    assert by_name["Total Rev"].table == ""  # bare -> measure or same-table column
    assert by_name["Revenue"].table == "FactSales"  # qualified column
    assert by_name["Date"].table == "Dim Date"  # quoted-table column


def test_bracket_refs_ignores_brackets_inside_strings():
    refs = bracket_refs(mask_dax('IF(x, "[NotARef]", [Real])'))
    assert [r.name for r in refs] == ["Real"]


def test_mask_handles_backslash_terminated_string():
    # DAX has no backslash escapes; a string ending in '\' must still close.
    dax = 'M = "path C:\\" + [Real]'
    masked = mask_dax(dax)
    assert len(masked) == len(dax)
    assert [r.name for r in bracket_refs(masked)] == ["Real"]  # ref after string survives


def test_mask_handles_doubled_quote_escape():
    masked = mask_dax('IF(x = "he said ""hi""", [A], [B])')
    assert [r.name for r in bracket_refs(masked)] == ["A", "B"]


def test_comment_markers_inside_strings_do_not_blank_later_refs():
    # A `//`/`--`/`/*` inside a string literal (e.g. a URL) must not be treated
    # as a comment and blank out the real refs after it.
    masked = mask_dax('IF([Flag], "http://example.com", [Sales: Total])')
    assert [r.name for r in bracket_refs(masked)] == ["Flag", "Sales: Total"]

    masked = mask_dax('IF([Flag], "x -- y", [Sales: Total])')
    assert [r.name for r in bracket_refs(masked)] == ["Flag", "Sales: Total"]


def test_block_comment_delimiters_inside_strings_do_not_straddle():
    # `/*` and `*/` that live inside separate string literals must not be paired
    # into one giant block comment that swallows the ref between them.
    masked = mask_dax('"a /* b" & [c] & "d */ e"')
    assert [r.name for r in bracket_refs(masked)] == ["c"]
