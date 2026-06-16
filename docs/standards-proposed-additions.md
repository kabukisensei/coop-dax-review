# DAX Standards — proposed additions (review before merging)

Microsoft / Tabular Editor "Best Practice Analyzer" (BPA) and SQLBI guidance **not yet covered**
by `standards.md`. Kept separate so your authored canon stays pristine — merge what you agree
with. "Checkable" = the deterministic tool can enforce it.

## A. Every measure has a Format String (Checkable — model, high value)
Measures without an explicit format render inconsistently. Rule idea: `DAX-FORMAT-STRING`
(warning) — measure with no `formatString`. *Source: Tabular BPA "Measures should have a
format string".*

## B. Use `DIVIDE()` instead of `/` (Checkable — text, high value)
`/` errors / returns Infinity on divide-by-zero; `DIVIDE()` handles it. Rule idea:
`DAX-USE-DIVIDE` (warning) — a `/` operator between expressions in a measure.

## C. Avoid `IFERROR` / `ISERROR` (Checkable — text)
They mask real errors and hurt performance; prefer `DIVIDE` / proper handling. Rule idea:
`DAX-AVOID-IFERROR` (info).

## D. Hide foreign-key / relationship columns (Checkable — model)
Columns used only in relationships should be hidden from report view. Rule idea:
`DAX-HIDE-FK-COLUMNS` (info) — a column on the "many" side of a relationship that is visible.

## E. Key columns: `summarizeBy = none` (Checkable — model)
Numeric key columns shouldn't auto-aggregate. Rule idea: `DAX-KEY-SUMMARIZEBY-NONE` (info).

## F. Use Display Folders when a table has many measures (Checkable — model, info)
Improves model usability. Rule idea: `DAX-DISPLAY-FOLDERS` — table with > N measures and no
display folders set.

## G. Avoid implicit measures (Checkable — model/agent)
Prefer explicit measures over drag-to-aggregate columns. Largely a modeling-discipline call →
mostly `agent_review`, but visible numeric columns with default summarization can be flagged.

## H. Avoid floating-point (`double`) for keys/amounts needing exactness (Checkable — model)
Use `int64`/`decimal`. Rule idea: `DAX-NO-FLOAT-KEYS` (info) — relationship column typed double.

---
*References already in `standards.md` §14 (skills-for-fabric) plus Tabular Editor BPA rules and
SQLBI guidance. When the reviewer adds a rule for any item above, cite it as the `standard_ref`.*
