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
    SCAN_EMPTY,  # a scan found no input files at all under a given path
    SYNTAX_ERROR,  # input that fails the tool's own syntax validation
    Diagnostic,
)

# SCAN_EMPTY / SYNTAX_ERROR now live in core (coop-review-core#1) and are
# re-exported above. For this tool, SYNTAX_ERROR is a measure body or
# calculated-column expression that fails cheap structural DAX validation
# (unbalanced parens/brackets, an unterminated string/block comment, an empty
# body) — "error" by default, tunable via the rules.yml `syntax_errors` knob and
# an inline `coop-dax-review:ignore syntax` directive.
