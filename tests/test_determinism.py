"""The output contract is byte-stable: same input -> identical JSON, twice."""

from pathlib import Path

from coop_dax_review import __version__
from coop_dax_review.cli import build_catalogs, discover_inputs
from coop_dax_review.engine import run_rules
from coop_dax_review.report import json_text
from coop_dax_review.rules import all_rules

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _render() -> str:
    tmdl, bim, pbit, pbix = discover_inputs((str(FIXTURES),))
    result = run_rules(build_catalogs(tmdl, bim), all_rules())
    return json_text(result, version=__version__, standards={"path": "p", "sha256": "abc"})


def test_json_is_byte_identical_across_runs():
    assert _render() == _render()


def test_json_is_pure_ascii():
    # ensure_ascii=True so the § marks/em-dashes are safe on a legacy console.
    _render().encode("ascii")
