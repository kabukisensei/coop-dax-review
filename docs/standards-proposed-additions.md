# DAX Standards — proposed additions (historical candidate list — all adopted)

**Historical note:** every item below (A–H) was adopted into `docs/standards.md` and implemented in
the live rule registry. This file is kept only as the record of where these best-practice rules came
from. Each item is annotated with the section and rule id it shipped as. Microsoft / Tabular Editor
"Best Practice Analyzer" (BPA) and SQLBI guidance was the source; "Checkable" = the deterministic
tool enforces it.

## A. Every measure has a Format String (Checkable — model, high value)
Measures without an explicit format render inconsistently. **Adopted → §15 `DAX-FORMAT-STRING`
(warning)** — measure with no `formatString`. *Source: Tabular BPA "Measures should have a
format string".*

## B. Use `DIVIDE()` instead of `/` (Checkable — text, high value)
`/` errors / returns Infinity on divide-by-zero; `DIVIDE()` handles it. **Adopted → §14
`DAX-USE-DIVIDE` (warning)** — a `/` operator between expressions in a measure.

## C. Avoid `IFERROR` / `ISERROR` (Checkable — text)
They mask real errors and hurt performance; prefer `DIVIDE` / proper handling. **Adopted → §24
`DAX-IFERROR-WRAPPING`** — narrowed to arithmetic wrapping (raised info → warning).

## D. Hide foreign-key / relationship columns (Checkable — model)
Columns used only in relationships should be hidden from report view. **Adopted → §17
`DAX-HIDE-FK-COLUMNS` (info)** — a column on the "many" side of a relationship that is visible.

## E. Key columns: `summarizeBy = none` (Checkable — model)
Numeric key columns shouldn't auto-aggregate. **Adopted → §18 `DAX-KEY-SUMMARIZEBY-NONE` (info)**.

## F. Use Display Folders when a table has many measures (Checkable — model, info)
Improves model usability. **Adopted → §19 `DAX-DISPLAY-FOLDERS`** — table with > N measures and no
display folders set.

## G. Avoid implicit measures (Checkable — model/agent)
Prefer explicit measures over drag-to-aggregate columns. **Adopted → §20 `DAX-IMPLICIT-MEASURE`** —
visible numeric columns with default summarization are flagged.

## H. Avoid floating-point (`double`) for keys/amounts needing exactness (Checkable — model)
Use `int64`/`decimal`. **Adopted → §16 `DAX-NO-FLOAT-KEYS` (info)** — relationship column typed double.

---
*All eight candidates above are now part of `docs/standards.md` (§14–§20, §24) and implemented in the
live rule registry; each rule carries its section as the `standard_ref`.*
