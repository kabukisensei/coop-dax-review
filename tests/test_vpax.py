import json
import zipfile
from pathlib import Path

from coop_dax_review.model import ModelCatalog, Table, Column
from coop_dax_review.parsers.vpax import load_vpax, apply_vpax_stats


def _create_synthetic_vpax(path: Path):
    dax_vpa_view = {
        "Model": {
            "Tables": [
                {
                    "TableName": "Sales",
                    "Columns": [
                        {
                            "ColumnName": "OrderNo",
                            "ColumnCardinality": 1500000,
                            "DataSize": 8000000,
                            "DictionarySize": 2000000,
                        },
                        {
                            "ColumnName": "Amount",
                            "ColumnCardinality": 5000,
                            "DataSize": 4000000,
                            "DictionarySize": 50000,
                        },
                    ],
                },
                {
                    "TableName": "DimDate",
                    "Columns": [
                        {
                            "ColumnName": "DateKey",
                            "ColumnCardinality": 3650,
                            "DataSize": 100000,
                            "DictionarySize": 20000,
                        }
                    ],
                },
            ]
        }
    }
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("DaxVpaView.json", json.dumps(dax_vpa_view).encode("utf-16-le"))


def test_load_vpax(tmp_path):
    vpax_file = tmp_path / "test.vpax"
    _create_synthetic_vpax(vpax_file)

    stats = load_vpax(vpax_file)
    assert "sales" in stats
    assert "orderno" in stats["sales"]
    assert stats["sales"]["orderno"]["cardinality"] == 1500000
    assert stats["sales"]["orderno"]["size_bytes"] == 10000000

    assert "dimdate" in stats
    assert "datekey" in stats["dimdate"]
    assert stats["dimdate"]["datekey"]["cardinality"] == 3650


def test_apply_vpax_stats(tmp_path):
    vpax_file = tmp_path / "test.vpax"
    _create_synthetic_vpax(vpax_file)

    catalog = ModelCatalog(
        name="TestModel",
        tables=[
            Table(
                name="Sales",
                columns=[
                    Column(name="OrderNo", data_type="string"),
                    Column(name="Amount", data_type="double"),
                ],
            ),
            Table(name="DimDate", columns=[Column(name="DateKey", data_type="int64")]),
        ],
    )

    apply_vpax_stats([catalog], vpax_file)

    sales = catalog.tables[0]
    assert sales.columns[0].cardinality == 1500000
    assert sales.columns[0].size_bytes == 10000000
    assert sales.columns[1].cardinality == 5000

    dimdate = catalog.tables[1]
    assert dimdate.columns[0].cardinality == 3650
    assert not catalog.diagnostics


def test_apply_vpax_stats_stale(tmp_path):
    vpax_file = tmp_path / "test.vpax"
    _create_synthetic_vpax(vpax_file)

    catalog = ModelCatalog(
        name="TestModel",
        tables=[
            Table(
                name="Sales",
                columns=[
                    Column(name="OrderNo", data_type="string"),
                    Column(name="MissingInVpax", data_type="string"),
                ],
            )
        ],
    )

    apply_vpax_stats([catalog], vpax_file)
    assert len(catalog.diagnostics) == 1
    diag = catalog.diagnostics[0]
    assert diag.severity == "warning"
    assert diag.category == "vpax_stale"
    assert "MissingInVpax" in diag.message
