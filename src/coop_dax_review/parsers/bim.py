"""model.bim (Tabular Object Model JSON) parsing into a :class:`ModelCatalog`.

Same catalog as the TMDL parser, sourced from the legacy single-file JSON
model format. JSON has no meaningful per-object line numbers, so findings on
a .bim model carry ``line=0`` and point at the file as a whole.
"""

from __future__ import annotations

import json

from coop_dax_review.model import CalculationItem, Column, Measure, ModelCatalog, Relationship, Table


def _expression_text(expression) -> str:
    if isinstance(expression, list):
        return "\n".join(str(part) for part in expression)
    return str(expression or "")


def build_catalog_from_dict(data: dict, file: str) -> ModelCatalog:
    """Convert a TOM JSON dictionary into a ModelCatalog."""

    model = data.get("model") or {}
    model_name = data.get("name") or model.get("name") or "model"
    catalog = ModelCatalog(name=model_name, file=file)
    table_modes: dict[str, str] = {}
    for table in model.get("tables") or []:
        if not isinstance(table, dict):
            continue
        table_name = table.get("name") or ""
        if not table_name:
            continue
        columns: list[Column] = []
        is_date = False
        for column in table.get("columns") or []:
            if not isinstance(column, dict) or not column.get("name"):
                continue
            category = str(column.get("dataCategory") or "")
            if category.lower() == "time":
                is_date = True
            columns.append(
                Column(
                    name=column["name"],
                    data_type=str(column.get("dataType") or ""),
                    is_calculated=column.get("type") == "calculated",
                    data_category=category,
                    expression=_expression_text(column.get("expression")),
                    is_hidden=bool(column.get("isHidden")),
                    summarize_by=str(column.get("summarizeBy") or ""),
                )
            )
        # Storage mode lives on the partition(s).
        mode = ""
        partitions = [p for p in (table.get("partitions") or []) if isinstance(p, dict)]
        for partition in partitions:
            source = partition.get("source") or {}
            if partition.get("mode"):
                mode = partition["mode"]
            elif isinstance(source, dict) and source.get("type") == "entity":
                mode = "directLake"
        annotations = {
            str(a.get("name") or "").lower() for a in table.get("annotations") or [] if isinstance(a, dict)
        }
        if "__pbi_templatedatetable" in annotations:
            is_date = True
        first_source = (partitions[0].get("source") or {}) if partitions else {}
        is_calc_table = isinstance(first_source, dict) and first_source.get("type") == "calculated"
        table_modes[table_name] = mode
        catalog.tables.append(
            Table(
                name=table_name,
                file=file,
                columns=columns,
                storage_mode=mode,
                is_date_table=is_date,
                is_hidden=bool(table.get("isHidden")),
                is_calculated=is_calc_table,
                # a calculated table's DAX lives on its partition source (issue #5)
                expression=_expression_text(first_source.get("expression")) if is_calc_table else "",
            )
        )
        for measure in table.get("measures") or []:
            if not isinstance(measure, dict) or not measure.get("name"):
                continue
            fmt = measure.get("formatString") or ""
            if not fmt and measure.get("formatStringDefinition"):
                fmt = "<dynamic>"  # dynamic format-string expression
            catalog.measures.append(
                Measure(
                    name=measure["name"],
                    dax=_expression_text(measure.get("expression")),
                    table=table_name,
                    file=file,
                    format_string=str(fmt),
                    display_folder=str(measure.get("displayFolder") or ""),
                    is_hidden=bool(measure.get("isHidden")),
                    # TOM serializes a multi-line description as an array of strings.
                    description=_expression_text(measure.get("description")),
                )
            )
        # Calculation group items (issue #8): their DAX lives on the table's
        # calculationGroup.calculationItems[]. Kept out of `measures` on purpose.
        calc_group = table.get("calculationGroup")
        if isinstance(calc_group, dict):
            for item in calc_group.get("calculationItems") or []:
                if not isinstance(item, dict) or not item.get("name"):
                    continue
                item_fmt = "<dynamic>" if item.get("formatStringExpression") else ""
                catalog.calculation_items.append(
                    CalculationItem(
                        name=item["name"],
                        dax=_expression_text(item.get("expression")),
                        table=table_name,
                        file=file,
                        format_string=item_fmt,
                    )
                )
    for rel in model.get("relationships") or []:
        if not isinstance(rel, dict) or not (rel.get("fromTable") and rel.get("toTable")):
            continue
        catalog.relationships.append(
            Relationship(
                from_table=rel["fromTable"],
                from_column=rel.get("fromColumn", ""),
                to_table=rel["toTable"],
                to_column=rel.get("toColumn", ""),
                cross_filter="both"
                if str(rel.get("crossFilteringBehavior") or "").lower() == "bothdirections"
                else "single",
                is_active=rel.get("isActive", True),
                file=file,
            )
        )
    return catalog


def parse_bim_model(file: str, text: str) -> ModelCatalog:
    """Parse one ``.bim`` file's JSON into a catalog. A JSON error is raised to
    the caller, which records it as a diagnostic."""
    data = json.loads(text)
    return build_catalog_from_dict(data, file)
