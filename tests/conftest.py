"""Make the src layout importable when the package isn't installed, and give
tests small helpers for building catalogs from inline DAX/TMDL."""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest  # noqa: E402

from coop_dax_review.model import Column, Measure, ModelCatalog, Relationship, Table  # noqa: E402


@pytest.fixture
def make_catalog():
    """Build a ModelCatalog from keyword lists of measures/tables/relationships.

    ``measures`` is a list of ``(name, dax)`` (optionally ``(name, dax, table)``).
    ``tables`` is a list of ``(name, [column_names])``.
    ``relationships`` is a list of dicts forwarded to ``Relationship``.
    """

    def _build(*, name="Test", measures=(), tables=(), relationships=(), date_table=None):
        cat = ModelCatalog(name=name, file=f"{name}.tmdl")
        for spec in measures:
            mname, dax = spec[0], spec[1]
            table = spec[2] if len(spec) > 2 else ""
            cat.measures.append(Measure(name=mname, dax=dax, table=table, file=cat.file, line=1))
        for tname, cols in tables:
            cat.tables.append(
                Table(
                    name=tname,
                    file=cat.file,
                    columns=[Column(name=c) for c in cols],
                    is_date_table=(tname == date_table),
                )
            )
        for rel in relationships:
            cat.relationships.append(Relationship(file=cat.file, **rel))
        return cat

    return _build
