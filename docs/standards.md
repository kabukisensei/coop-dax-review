# DAX Standards

## Core Philosophy: The Hybrid Standard

These standards follow a **hybrid DAX methodology**: the readable, step-debuggable,
variable-first approach from Greg Deckler's *DAX for Humans* (VAR-first structure,
isolated table variables, explicit iterators), combined with pragmatic, intentional
use of `CALCULATE()` reserved for the cases where filter or relationship manipulation
actually requires it.

The default mental model, in order:

1. **Build intermediate results as variables** (§2, §27). Every non-trivial measure is a
   sequence of named steps you can inspect, return individually, and debug.
2. **Filter with table variables and iterate explicitly** (§28). Routine local filters
   build a `VAR _FilteredTable = FILTER(...)` and aggregate over it with `SUMX`,
   `COUNTX`, or `AVERAGEX`. No `CALCULATE` required.
3. **Reach for `CALCULATE` only with intent** (§30). It is allowed for exactly three
   jobs: global filter-state overrides, relationship/security overrides, and deliberate
   context transition.

### Directive keywords

- **MUST** / **MUST NOT**: enforced, non-negotiable rules.
- **PREFER**: the default choice; deviate only with a stated reason in a comment.
- **ALLOW**: a permitted exception under the stated conditions.

### Tier map

| Tier | Principle | Sections |
|------|-----------|----------|
| 1. Variable-first architecture (default) | VAR-first, table variables, explicit iterators, no gratuitous `CALCULATE` | §2, §27, §28, §29 |
| 2. Intentional `CALCULATE` (allowed exceptions) | Filter-state overrides, relationship/security overrides, deliberate context transition | §30 (supported by §4, §5, §7, §8, §23) |
| 3. Banned anti-patterns | Implicit context transition, magic numbers, nested `CALCULATE`, auto date/time, `EARLIER`, `IFERROR` wrapping | §3, §21, §22, §24, §31, §32 |
| Model hygiene (supporting) | Naming, schema shape, format strings, keys, folders | §1, §6, §14–§20, §25 |

## 1. Naming Conventions

| Type | Pattern | Example |
|------|---------|---------|
| Measures | `[Category: Name]` | `[Sales: Total Revenue]`, `[Customer: Active Count]` |
| Calculated Columns | `PascalCase` | `FullName`, `IsActive` |
| Tables | `PascalCase` | `DimCustomer`, `FactSales` |

### Column vs. Measure References

- **Columns:** Always prefix with table name: `Table[Column]`
- **Measures:** Never prefix with table name: `[Measure Name]`

```dax
-- Good: Column prefixed, measure not prefixed
VAR _CustomerRevenue =
    CALCULATE(
        [Sales: Total Revenue],
        DimCustomer[CustomerId] = 123
    )

-- Bad: Measure prefixed with table, column not prefixed
VAR _CustomerRevenue =
    CALCULATE(
        FactSales[Sales: Total Revenue],  -- Wrong: measures don't get table prefix
        [CustomerId] = 123                -- Wrong: columns need table prefix
    )
```

## 2. VAR/RETURN Structure (Mandatory)

Always use `VAR`/`RETURN` for readability and to avoid repeated logic.

```dax
-- Good: VAR/RETURN with clear variable names
Sales: Total Revenue =
VAR _SelectedPeriod =
    DATESBETWEEN(
        DimDate[Date],
        MIN(DimDate[Date]),
        MAX(DimDate[Date])
    )
VAR _Result =
    CALCULATE(
        SUM(FactSales[Revenue]),
        _SelectedPeriod
    )
RETURN
    _Result

-- Bad: Dense one-liner
Sales: Total Revenue = CALCULATE(SUM(FactSales[Revenue]), DATESBETWEEN(DimDate[Date], MIN(DimDate[Date]), MAX(DimDate[Date])))
```

## 3. No Nested CALCULATE

Never nest `CALCULATE` inside another `CALCULATE`. Use `VAR` to break it apart.

```dax
-- Good: Break into VARs, single CALCULATE
Sales: Revenue YTD =
VAR _CurrentYear =
    CALCULATE(
        [Sales: Total Revenue],
        DATESYTD(DimDate[Date])
    )
VAR _PreviousYear =
    CALCULATE(
        [Sales: Total Revenue],
        SAMEPERIODLASTYEAR(DimDate[Date])
    )
VAR _Result =
    _CurrentYear - _PreviousYear
RETURN
    _Result

-- Bad: Nested CALCULATE
Sales: Revenue YTD =
    CALCULATE(
        CALCULATE(
            SUM(FactSales[Revenue]),
            DATESYTD(DimDate[Date])
        ),
        SAMEPERIODLASTYEAR(DimDate[Date])
    )
```

## 4. Filter Columns, Not Tables

Prefer filtering columns (not entire tables) in `CALCULATE`.

> **Hybrid note (§28, §30):** a predicate passed as a `CALCULATE` filter argument
> *replaces* the outer filter on that column: it is a filter-state override. Use this
> form only when that override is the intent (§30). For routine local filtering that
> should respect the existing filter context, use a table variable with an explicit
> iterator instead (§28). When `CALCULATE` is justified, boolean column predicates
> remain the endorsed filter-argument form; `FILTER(<table>, ...)` as a filter argument
> stays banned.

```dax
-- Good: Filter on column
Sales: Enterprise Revenue =
CALCULATE(
    [Sales: Total Revenue],
    DimCustomer[MarketSegment] = "Enterprise"
)

-- Bad: Filter on entire table
Sales: Enterprise Revenue =
CALCULATE(
    [Sales: Total Revenue],
    FILTER(
        DimCustomer,
        DimCustomer[MarketSegment] = "Enterprise"
    )
)
```

## 5. KEEPFILTERS for Outer Filter Preservation

Use `KEEPFILTERS` when preserving outer filter shapes is important.

```dax
-- Good: Preserves existing filters on ProductCategory
Sales: Premium Products =
CALCULATE(
    [Sales: Total Revenue],
    KEEPFILTERS(DimProduct[ProductTier] = "Premium")
)

-- Bad: Overwrites outer filters on ProductTier
Sales: Premium Products =
CALCULATE(
    [Sales: Total Revenue],
    DimProduct[ProductTier] = "Premium"
)
```

## 6. Star Schema Preferred

- Prefer **star schema** over snowflake for Power BI semantic models
- Keep dimension tables flat and denormalized
- Avoid chaining relationships through intermediate tables

## 7. Bidirectional Relationships

- **Avoid bidirectional physical relationships by default**
- If cross-filtering is needed, use targeted `CROSSFILTER` inside measures

```dax
-- Good: Use CROSSFILTER in measure, not model
Sales: Budget Allocation =
CALCULATE(
    [Sales: Total Revenue],
    CROSSFILTER(FactSales[ProductId], DimProduct[ProductId], Both)
)
```

## 8. Marked Date Table Required

Always require a contiguous **marked Date table** for time intelligence.

```dax
-- Good: Uses marked date table
Sales: Revenue YTD =
CALCULATE(
    [Sales: Total Revenue],
    DATESYTD(DimDate[Date])
)
```

## 9. Context Transition Awareness

- Avoid relying on context transition over non-unique/duplicate-row tables
- Be aware of hidden `CALCULATE` around measure references inside iterators

```dax
-- Caution: Context transition happens here
-- Each row in the iterator triggers a context transition
Sales: Average Customer Revenue =
AVERAGEX(
    VALUES(DimCustomer[CustomerId]),
    [Sales: Total Revenue]  -- Implicit CALCULATE wraps this measure
)
```

## 10. Workflow Philosophy

### Before Writing a Measure

- [ ] Confirm business definition and grain
- [ ] Identify required filter behavior (respect/ignore which slicers)
- [ ] Verify Date table requirements for time logic

### Start Simple, Then Complexify

1. Start from a standard baseline
2. Complexify one step at a time
3. Test each change before adding more

### Debug Before Rewriting

- Isolate and filter-debug a failing measure context before rewriting logic
- Use `VAR` and basic functions to inspect intermediate values

### Prefer Simple Functions

- Use `VAR` and basic functions as much as possible
- Use `CALCULATE` only when necessary
- **No nested CALCULATE**

## 11. Validation Checklist

After writing a measure, validate before committing:

- [ ] **Test base measure first** — Does it work with no filters?
- [ ] **Test with/without key slicers** — Does filter behavior match requirements?
- [ ] **Test edge cases** — Blank values, zero, no rows
- [ ] **Compare against known control totals** — Does it match expected values?

## 12. Header Comments (Complex Measures)

```dax
/*
  Measure: [Sales: Total Revenue]
  Purpose: Sum of revenue across all sales transactions
  Context: Works in any filter context
  Dependencies: FactSales[Revenue], DimDate[Date]
  Author: Aaron Jennings
  Date: 2026-06-01
*/
```

## 13. Checklist Before Committing DAX

- [ ] Columns prefixed with table names: `Table[Column]`
- [ ] Measures NOT prefixed with table names: `[Measure]`
- [ ] VAR/RETURN structure used
- [ ] Multiline formatting with indentation
- [ ] No nested CALCULATE
- [ ] Filters on columns, not tables
- [ ] KEEPFILTERS used where outer filters must be preserved
- [ ] Star schema maintained
- [ ] No bidirectional relationships (use CROSSFILTER in measures)
- [ ] Marked Date table for time intelligence
- [ ] Context transition considered
- [ ] Variables named with a leading underscore: `VAR _Name` (§27)
- [ ] Routine local filters use table variables + explicit iterators (§28)
- [ ] Every `CALCULATE` justified under §30; none gratuitous (§29)
- [ ] No magic numbers or inline business literals (§31)
- [ ] Context transitions intentional and commented (§32)
- [ ] Comments on complex logic
- [ ] **Validation completed** (base measure, slicers, edge cases, control totals)
- [ ] **Direct Lake constraints verified** (no calculated columns, table names match exactly)
- [ ] **TMDL format used** for deployment (not TMSL)

## 14. Use DIVIDE() Instead of /

Use `DIVIDE()` for division, not the `/` operator. `/` raises / returns infinity on
divide-by-zero; `DIVIDE()` returns a blank (or a supplied alternate) instead.

```dax
-- Good: safe division
Sales: Margin % =
DIVIDE(
    [Sales: Profit],
    [Sales: Total Revenue]
)

-- Bad: / errors or returns Infinity when the denominator is 0 / blank
Sales: Margin % = [Sales: Profit] / [Sales: Total Revenue]
```

## 15. Measure Format Strings

Every measure should declare an explicit `formatString`. Without one, the same measure
renders inconsistently across visuals and reports.

```tmdl
measure 'Sales: Total Revenue' = SUM(FactSales[Revenue])
    formatString: "\$#,0"
```

## 16. Relationship Key Column Types

Relationship key columns should be integer (`int64`) or `decimal`, never floating-point
(`double`). Floating-point keys can fail to match exactly, silently dropping rows from a join.

```tmdl
-- Good: integer surrogate key on both sides of the relationship
column CustomerKey
    dataType: int64

-- Bad: a double-typed key column used in a relationship
column CustomerKey
    dataType: double
```

## 17. Hide Foreign-Key Columns

Relationship key columns on the "many" side (foreign keys) are plumbing — hide them from report
view so report authors don't drag a raw key onto a visual.

```tmdl
-- Good: the FK column used by the relationship is hidden
column CustomerKey
    dataType: int64
    isHidden: true
```

## 18. Key Columns Should Not Auto-Aggregate

A numeric relationship key column with default summarization can be dragged onto a visual and
silently summed. Set `summarizeBy: none` on key columns.

```tmdl
-- Good: key column does not auto-aggregate
column CustomerKey
    dataType: int64
    summarizeBy: none
```

## 19. Use Display Folders for Measure-Heavy Tables

A table with many measures and no display folders is hard to navigate. Group measures into display
folders once a table carries more than a handful.

```tmdl
measure 'Sales: Total Revenue' = SUM(FactSales[Revenue])
    displayFolder: "Revenue"
```

## 20. Prefer Explicit Measures Over Implicit Ones

Prefer explicit measures over drag-to-aggregate (implicit) measures. A visible numeric column with
default summarization invites implicit aggregation instead of a defined, documented measure — hide
such columns or set `summarizeBy: none` and add an explicit measure.

## 21. Disable Auto Date/Time

Disable Power BI Desktop's **auto date/time** option. When it is on, Power BI silently creates one
hidden date-hierarchy table for every date column in the model (named `LocalDateTable_<guid>`, with
a `DateTableTemplate_<guid>` template). These auto-tables bloat the model, are not maintainable, and
undermine the §8 marked-Date-table discipline — time intelligence should flow through the model's
own contiguous, marked Date dimension, not per-column auto-hierarchies.

The presence of a `LocalDateTable_*` or `DateTableTemplate_*` table in a published semantic model is
a reliable, deterministic signal that auto date/time was left on. Turn the option off (File →
Options → Data Load → Time intelligence), remove the auto-tables, and reference a single marked Date
table (§8) for all time-intelligence calculations.

## 22. Replace EARLIER with VAR

Never use `EARLIER`/`EARLIEST` in new DAX. They are the legacy pre-VAR way to reach an outer row
context: they read as a puzzle, and they break silently when the surrounding code adds another row
context level. Capture the outer row's value in a `VAR` before entering the inner row context —
§2 already mandates VAR/RETURN structure, and a variable makes the intent explicit.

```dax
-- Good: capture the outer row's value in a VAR
RunningTotal =
VAR _CurrentDate = FactSales[OrderDate]
RETURN
    CALCULATE(
        SUM(FactSales[Revenue]),
        FILTER(
            ALL(FactSales),
            FactSales[OrderDate] <= _CurrentDate
        )
    )

-- Bad: EARLIER reaches back one row context implicitly
RunningTotal =
CALCULATE(
    SUM(FactSales[Revenue]),
    FILTER(
        ALL(FactSales),
        FactSales[OrderDate] <= EARLIER(FactSales[OrderDate])
    )
)
```

## 23. No Dead Inactive Relationships

An inactive relationship (`isActive: false`) exists to be activated on demand with
`USERELATIONSHIP()`. One that no measure, calculated column, or calculation item ever activates is
dead modeling weight: it confuses maintainers, slows model comprehension, and often marks a missed
active path. Either use it where the alternate path is needed, or remove it.

```dax
-- Good: the inactive DimDate[Date] -> FactSales[ShipDate] relationship is used on demand
Sales: Revenue by Ship Date =
CALCULATE(
    [Sales: Total Revenue],
    USERELATIONSHIP(FactSales[ShipDate], DimDate[Date])
)
```

## 24. Don't Wrap Arithmetic in IFERROR

Don't wrap division or other arithmetic in `IFERROR`. It hides **every** error — including the
real data and logic bugs you want surfaced — and forces the engine into slower row-by-row error
handling. For divide-by-zero, use `DIVIDE()` (§14); for expected blanks, test the inputs instead
of swallowing the failure.

```dax
-- Good: DIVIDE handles the only expected failure (a zero/blank denominator)
Sales: Margin % =
DIVIDE(
    [Sales: Profit],
    [Sales: Total Revenue]
)

-- Bad: IFERROR hides real errors and is slower
Sales: Margin % =
IFERROR(
    [Sales: Profit] / [Sales: Total Revenue],
    BLANK()
)
```

## 25. Measure Descriptions

Every **visible** measure should carry a description: it is the documentation report authors see
on hover in the field list, and it is what Copilot/Q&A read to choose and explain measures. In
TMDL a description is a `///` doc-comment directly above the declaration; in a `.bim` it is the
`description` property. Hidden measures (internal helpers) are exempt.

```tmdl
/// Total revenue across all sales transactions, before returns.
measure 'Sales: Total Revenue' = SUM(FactSales[Revenue])
```

## 27. Variable Names: Leading Underscore (MUST)

Every local variable MUST be named with a leading underscore (`_Name`). The prefix makes
local variables instantly distinguishable from column references (`Table[Column]`) and
measure references (`[Measure]`), and it keeps the step-by-step dependency chain obvious
when reading a measure top to bottom.

> Convention note: *DAX for Humans* writes these with a double underscore (`__Table`,
> `__Result`). This standard adopts a single leading underscore; either prefix achieves
> the same goal, and consistency within the model is what matters.

**BEFORE (Non-Compliant)**

```dax
Sales: YoY Growth =
VAR CurrentYearSales =
    SUM(FactSales[Revenue])
VAR PriorYearSales =
    CALCULATE(
        SUM(FactSales[Revenue]),
        SAMEPERIODLASTYEAR(DimDate[Date])
    )
RETURN
    CurrentYearSales - PriorYearSales
```

**AFTER (Compliant)**

```dax
Sales: YoY Growth =
VAR _CurrentYearSales =
    SUM(FactSales[Revenue])
VAR _PriorYearSales =
    CALCULATE(
        SUM(FactSales[Revenue]),
        SAMEPERIODLASTYEAR(DimDate[Date])
    )
RETURN
    _CurrentYearSales - _PriorYearSales
```

## 28. Table Variables + Explicit Iterators for Routine Local Filters (PREFER)

A *routine local filter* is a predicate over the data itself (a quantity threshold, a
category membership, a row-level condition) that does not need to change the report's
filter state. For these you MUST default to an isolated table variable aggregated by an
explicit iterator, not `CALCULATE`.

Why: `FILTER(...)` used as a table function iterates the **already-filtered** table, so
the existing slicer/page context is respected. The same predicate passed as a
`CALCULATE` filter argument would **replace** the outer filter on that column (§4).

- PREFER `VAR _FilteredTable = FILTER(...)` + `SUMX` / `COUNTX` / `AVERAGEX` / `MINX` /
  `MAXX` for routine local filters.
- MUST NOT use `CALCULATE` for a routine local filter (§29, §30).
- Keep the table variable as narrow as practical: filter early, iterate only what the
  aggregation needs.

**BEFORE (Non-Compliant)**

```dax
Sales: Large Order Revenue =
CALCULATE(
    SUM(FactSales[Revenue]),
    FILTER(
        FactSales,
        FactSales[Quantity] > 10
    )
)
-- Two problems: CALCULATE for a routine local filter, and FILTER(table) as a
-- filter argument (§4). The predicate also silently replaces any outer
-- filter on FactSales[Quantity].
```

**AFTER (Compliant)**

```dax
Sales: Large Order Revenue =
VAR _LargeOrderQuantityThreshold = 10
VAR _LargeOrders =
    FILTER(
        FactSales,
        FactSales[Quantity] > _LargeOrderQuantityThreshold
    )
VAR _Result =
    SUMX(_LargeOrders, FactSales[Revenue])
RETURN
    _Result
```

Multi-condition local filters stay in the same shape:

```dax
Sales: West Large Order Revenue =
VAR _LargeOrderQuantityThreshold = 10
VAR _WestRegion = "West"
VAR _TargetOrders =
    FILTER(
        FactSales,
        FactSales[Quantity] > _LargeOrderQuantityThreshold
            && RELATED(DimRegion[RegionName]) = _WestRegion
    )
VAR _Result =
    SUMX(_TargetOrders, FactSales[Revenue])
RETURN
    _Result
```

Debugging tip from *DAX for Humans*: to inspect a table variable, temporarily change the
`RETURN` to `TOCSV(_TargetOrders)` and drop the measure in a Card visual. You see the
exact rows the variable holds, which is what makes this pattern step-debuggable. Restore
the real `RETURN` before committing.

## 29. No Gratuitous CALCULATE (MUST NOT)

MUST NOT wrap a basic scalar expression or straightforward aggregation in `CALCULATE`
when no filter, relationship, or context-transition behavior is needed. A
single-argument `CALCULATE` in a plain measure adds nothing the engine does not already
do, and it signals to the reader that a filter manipulation exists when none does.

**BEFORE (Non-Compliant)**

```dax
Sales: Total Revenue =
CALCULATE(
    SUM(FactSales[Revenue])
)
```

**AFTER (Compliant)**

```dax
Sales: Total Revenue =
SUM(FactSales[Revenue])
```

Note: a single-argument `CALCULATE` inside a **row context** is not gratuitous; it is
context transition, governed by §30 (case 3) and §32, and must be intentional.

## 30. Intentional CALCULATE: The Three Allowed Uses (ALLOW)

`CALCULATE` is ALLOWED only when at least one of the following is true. If none apply,
the measure belongs in the variable-first form (§28).

1. **Global filter-state overrides.** Manipulating the active page/visual slicer context
   with `REMOVEFILTERS()`, `ALL()`, `ALLEXCEPT()`, or `ALLSELECTED()`. This includes
   replacing the Date filter context for time intelligence (`DATESYTD`,
   `SAMEPERIODLASTYEAR`, `DATEADD`, `DATESBETWEEN`, …), which requires the marked Date
   table of §8.
2. **Relationship and security overrides.** Switching the active relationship with
   `USERELATIONSHIP()` (§23) or altering filter propagation with `CROSSFILTER()` (§7).
3. **Deliberate row-to-filter context transition.** In calculated columns or specialized
   row-level iterations where table-variable filtering (§28) is impractical (§9, §32).

Inside a justified `CALCULATE`, filter arguments follow §4 (boolean column predicates,
never `FILTER(<table>, ...)` where a predicate suffices) and §5 (`KEEPFILTERS` when the
outer filter shape must be preserved).

**BEFORE (Non-Compliant)**

```dax
Sales: Online Revenue =
CALCULATE(
    SUM(FactSales[Revenue]),
    FactSales[Channel] = "Online"
)
-- No slicer override intended, no relationship change, no context transition.
-- This is a routine local filter: write it as a table variable (§28).
```

**AFTER (Compliant): case 1, filter-state override**

```dax
Sales: Revenue % of All Regions =
VAR _RegionRevenue =
    SUM(FactSales[Revenue])
VAR _AllRegionRevenue =
    CALCULATE(
        SUM(FactSales[Revenue]),
        REMOVEFILTERS(DimRegion)
    )
RETURN
    DIVIDE(_RegionRevenue, _AllRegionRevenue)
```

**AFTER (Compliant): case 2, relationship override**

```dax
Sales: Revenue by Ship Date =
CALCULATE(
    [Sales: Total Revenue],
    USERELATIONSHIP(FactSales[ShipDate], DimDate[Date])
)
```

**AFTER (Compliant): case 3, deliberate context transition**

```dax
Sales: Average Revenue per Customer =
AVERAGEX(
    VALUES(DimCustomer[CustomerId]),
    [Sales: Total Revenue]  -- intentional context transition: one revenue value per customer
)
```

## 31. No Magic Numbers or Inline Business Literals (MUST NOT)

Any numeric or string literal that carries business meaning (thresholds, channel or
status codes, target values, scaling factors a reader could not guess) MUST be defined
as a named variable at the top of the measure, not embedded inline. The name documents
the business meaning and gives reviewers one place to change it.

Exempt: `0`, `1`, `100` in pure arithmetic (percent scaling), `BLANK()`, `TRUE()`,
`FALSE()`.

**BEFORE (Non-Compliant)**

```dax
Sales: Large Online Order Count =
VAR _LargeOrders =
    FILTER(
        FactSales,
        FactSales[Quantity] > 10
            && FactSales[Channel] = "Online"
    )
RETURN
    COUNTX(_LargeOrders, FactSales[OrderId])
```

**AFTER (Compliant)**

```dax
Sales: Large Online Order Count =
VAR _LargeOrderQuantityThreshold = 10
VAR _OnlineChannel = "Online"
VAR _LargeOrders =
    FILTER(
        FactSales,
        FactSales[Quantity] > _LargeOrderQuantityThreshold
            && FactSales[Channel] = _OnlineChannel
    )
RETURN
    COUNTX(_LargeOrders, FactSales[OrderId])
```

## 32. No Implicit Context Transition in Basic Measures (MUST NOT)

A measure reference (or a single-argument `CALCULATE`) inside an iterator wraps the
expression in a hidden `CALCULATE` and triggers context transition for every iterated
row (§9). MUST NOT rely on this accidentally:

- In routine aggregations, iterate explicit row-level expressions over table variables
  (§28) so no transition occurs at all.
- When per-row transition is the point of the measure (the §30 case 3 pattern, such as
  averaging a measure per customer), it is ALLOWED and MUST carry a comment stating the
  transition is intentional.

**BEFORE (Non-Compliant)**

```dax
Sales: Revenue Calc =
SUMX(
    FactSales,
    FactSales[Quantity] * [Sales: Average Unit Price]
    -- accidental transition: the measure reference re-evaluates per row
)
```

**AFTER (Compliant)**

```dax
Sales: Revenue Calc =
SUMX(
    FactSales,
    FactSales[Quantity] * RELATED(DimProduct[UnitPrice])
    -- explicit row-level expression; no context transition needed
)
```

## 26. References

- [Microsoft Fabric Skills for GitHub Copilot](https://github.com/microsoft/skills-for-fabric) — Official Microsoft-authored Fabric skills (MIT license)
- [Microsoft Fabric Semantic Model Authoring](https://github.com/microsoft/skills-for-fabric/tree/main/skills/semantic-model-authoring) — TMDL, DAX, deployment patterns
- [Microsoft Fabric DAX Guidelines](https://github.com/microsoft/skills-for-fabric/tree/main/skills/semantic-model-authoring/references/dax-guidelines.md) — Authoritative DAX guidance
- [Microsoft Fabric Direct Lake Guidelines](https://github.com/microsoft/skills-for-fabric/tree/main/skills/semantic-model-authoring/references/direct-lake-guidelines.md) — Direct Lake constraints
- [Microsoft Fabric Community Blog](https://community.fabric.microsoft.com/t5/Fabric-Updates-Blog/Fabric-Skills-for-GitHub-Copilot-Claude-and-CLI-built-by/ba-p/5190188) — Announcement and overview
- Greg Deckler, *DAX for Humans* (2025) — the variable-first, table-variable, explicit-iterator "No CALCULATE" methodology behind Tier 1 (§27–§29). Companion code: <https://github.com/gdeckler/DAX-For-Humans>
- [SQLBI](https://www.sqlbi.com) — CALCULATE-centric guidance; this standard keeps its filter-argument discipline (§4, §5) and context-transition rigor (§9, §32) while defaulting to variable-first authoring (§28)

> **Note:** Microsoft updates their skills repository regularly. This agent checks for updates weekly and patches new guidance into these standards as needed.
