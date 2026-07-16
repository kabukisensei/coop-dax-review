from collections import defaultdict
from typing import List

from coop_dax_review.finding import Finding
from coop_dax_review.model import normalize
from coop_dax_review.rules.base import EstateContext, Rule


def check_estate(ctx: EstateContext) -> List[Finding]:
    findings = []

    # group measures by normalize(name) -> dict[format_string, list[model_name]]
    measure_groups = defaultdict(lambda: defaultdict(list))

    for catalog in ctx.catalogs:
        for measure in catalog.measures:
            name = normalize(measure.name)
            fmt = measure.format_string
            measure_groups[name][fmt].append(catalog.name)

    for name, formats in measure_groups.items():
        if len(formats) > 1:
            models_involved = set(m for sublist in formats.values() for m in sublist)
            model_label = " <> ".join(sorted(models_involved))

            # describe the formats
            format_desc = []
            for fmt, models in formats.items():
                disp = f"'{fmt}'" if fmt else "no format"
                format_desc.append(f"{disp} in {', '.join(sorted(models))}")

            message = f"measure '{name}' has conflicting format strings: " + " vs. ".join(format_desc)
            findings.append(
                ctx.finding(models=model_label, object=name, message=message, fingerprint_key=name)
            )

    return findings


RULE = Rule(
    id="DAX-ESTATE-FORMAT-DRIFT",
    title="Format string drift",
    severity="warning",
    category="consistency",
    standard_ref="Estate Consistency",
    tier=2,
    kind="estate",
    check_estate=check_estate,
)
