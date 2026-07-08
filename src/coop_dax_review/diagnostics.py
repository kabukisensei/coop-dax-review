"""Processing diagnostics — re-exported from the shared ``coop-review-core``.

The Diagnostic model and category constants are tool-agnostic, so they live in
``coop_review_core.diagnostics`` and are re-exported here for backward-compatible
imports (``from coop_dax_review.diagnostics import Diagnostic`` still works).
"""

from coop_review_core.diagnostics import (  # noqa: F401
    BASELINE_STALE,
    CONFIG_UNKNOWN_RULE,
    DIAGNOSTIC_SEVERITIES,
    FILE_UNREADABLE,
    IGNORE_STALE,
    PARSE_DEGRADED,
    PARSE_FAILED,
    RULE_ERROR,
    Diagnostic,
)

# Tool-local category (not in core yet; mirrors coop-sql-review): a scan found
# no TMDL/.bim models at all under a given path — models_checked=0 must stay
# machine-distinguishable from "clean".
SCAN_EMPTY = "scan_empty"

# Tool-local category (mirrors coop-sql-review's SYNTAX_ERROR): a measure body or
# calculated-column expression that fails cheap structural DAX validation —
# unbalanced parens/brackets, an unterminated string or block comment, or an
# empty body. Malformed DAX like this would import broken into Power BI and, left
# unflagged, lets the text rules half-analyze the garbage. Severity is "error" by
# default; the rules.yml `syntax_errors: error|warning|off` knob can downgrade or
# disable it, and an inline `coop-dax-review:ignore syntax` directive suppresses a
# single occurrence.
SYNTAX_ERROR = "syntax_error"
