# DAX Standards

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
VAR CustomerRevenue =
    CALCULATE(
        [Sales: Total Revenue],
        DimCustomer[CustomerId] = 123
    )

-- Bad: Measure prefixed with table, column not prefixed
VAR CustomerRevenue =
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
VAR SelectedPeriod =
    DATESBETWEEN(
        DimDate[Date],
        MIN(DimDate[Date]),
        MAX(DimDate[Date])
    )
VAR Result =
    CALCULATE(
        SUM(FactSales[Revenue]),
        SelectedPeriod
    )
RETURN
    Result

-- Bad: Dense one-liner
Sales: Total Revenue = CALCULATE(SUM(FactSales[Revenue]), DATESBETWEEN(DimDate[Date], MIN(DimDate[Date]), MAX(DimDate[Date])))
```

## 3. No Nested CALCULATE

Never nest `CALCULATE` inside another `CALCULATE`. Use `VAR` to break it apart.

```dax
-- Good: Break into VARs, single CALCULATE
Sales: Revenue YTD =
VAR CurrentYear =
    CALCULATE(
        [Sales: Total Revenue],
        DATESYTD(DimDate[Date])
    )
VAR PreviousYear =
    CALCULATE(
        [Sales: Total Revenue],
        SAMEPERIODLASTYEAR(DimDate[Date])
    )
VAR Result =
    CurrentYear - PreviousYear
RETURN
    Result

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
VAR CurrentDate = FactSales[OrderDate]
RETURN
    CALCULATE(
        SUM(FactSales[Revenue]),
        FILTER(
            ALL(FactSales),
            FactSales[OrderDate] <= CurrentDate
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

## 26. References

- [Microsoft Fabric Skills for GitHub Copilot](https://github.com/microsoft/skills-for-fabric) — Official Microsoft-authored Fabric skills (MIT license)
- [Microsoft Fabric Semantic Model Authoring](https://github.com/microsoft/skills-for-fabric/tree/main/skills/semantic-model-authoring) — TMDL, DAX, deployment patterns
- [Microsoft Fabric DAX Guidelines](https://github.com/microsoft/skills-for-fabric/tree/main/skills/semantic-model-authoring/references/dax-guidelines.md) — Authoritative DAX guidance
- [Microsoft Fabric Direct Lake Guidelines](https://github.com/microsoft/skills-for-fabric/tree/main/skills/semantic-model-authoring/references/direct-lake-guidelines.md) — Direct Lake constraints
- [Microsoft Fabric Community Blog](https://community.fabric.microsoft.com/t5/Fabric-Updates-Blog/Fabric-Skills-for-GitHub-Copilot-Claude-and-CLI-built-by/ba-p/5190188) — Announcement and overview

> **Note:** Microsoft updates their skills repository regularly. This agent checks for updates weekly and patches new guidance into these standards as needed.
