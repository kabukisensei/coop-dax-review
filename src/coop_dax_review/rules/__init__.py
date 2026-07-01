"""Rule registry via auto-discovery.

Every rule lives in its own ``dax_*.py`` module exporting a module-level
``RULE``. Discovery imports each such module and collects its ``RULE``, so a
new rule is added by dropping in a file — no shared registry to edit (which
keeps parallel rule authoring conflict-free). Rules are returned sorted by id
for deterministic ordering.
"""

from __future__ import annotations

import importlib
import pkgutil

from coop_dax_review.rules.base import Rule, RuleContext

__all__ = ["Rule", "RuleContext", "all_rules"]


def all_rules() -> list[Rule]:
    """Every discovered rule, sorted by id.

    A ``dax_*`` module that doesn't export a module-level ``RULE = Rule(...)``
    raises instead of being silently skipped — a broken/misdeclared rule module
    would otherwise ship a linter that quietly stops enforcing that rule on
    every model (the exact failure mode auto-discovery risks).
    """
    rules: list[Rule] = []
    for info in pkgutil.iter_modules(__path__, prefix=f"{__name__}."):
        short = info.name.rsplit(".", 1)[1]
        if not short.startswith("dax_"):
            continue  # base/helpers are not rule modules
        module = importlib.import_module(info.name)
        rule = getattr(module, "RULE", None)
        if not isinstance(rule, Rule):
            raise TypeError(
                f"rule module {info.name} must export a module-level RULE = Rule(...); "
                f"found {type(rule).__name__}"
            )
        rules.append(rule)
    rules.sort(key=lambda r: r.id)
    return rules
