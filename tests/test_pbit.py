import zipfile
import json
from click.testing import CliRunner

from coop_dax_review.cli import cli
from coop_dax_review.parsers.pbit import parse_pbit_model

def test_pbit_parser(tmp_path):
    model_json = {
        "name": "TestModel",
        "model": {
            "tables": [
                {
                    "name": "Table1",
                    "columns": [
                        {"name": "Col1", "dataType": "string"}
                    ],
                    "measures": [
                        {"name": "Measure1", "expression": "SUM(Table1[Col1])"}
                    ]
                }
            ]
        }
    }
    
    pbit_path = tmp_path / "model.pbit"
    with zipfile.ZipFile(pbit_path, "w") as z:
        z.writestr("DataModelSchema", b'\xff\xfe' + json.dumps(model_json).encode("utf-16-le"))
        
    catalog = parse_pbit_model(str(pbit_path))
    assert catalog.name == "TestModel"
    assert len(catalog.tables) == 1
    assert catalog.tables[0].name == "Table1"
    assert len(catalog.measures) == 1
    assert catalog.measures[0].name == "Measure1"

def test_pbit_cli(tmp_path):
    model_json = {
        "name": "TestModel",
        "model": {
            "tables": [
                {
                    "name": "Table1",
                    "measures": [
                        {"name": "Measure1", "expression": "1 / 0"}
                    ]
                }
            ]
        }
    }
    
    pbit_path = tmp_path / "model.pbit"
    with zipfile.ZipFile(pbit_path, "w") as z:
        z.writestr("DataModelSchema", b'\xff\xfe' + json.dumps(model_json).encode("utf-16-le"))
        
    runner = CliRunner()
    res = runner.invoke(cli, ["check", str(pbit_path)])
    
    assert res.exit_code == 0
    assert "models checked: 1" in res.output

def test_pbix_diagnostic(tmp_path):
    pbix_path = tmp_path / "model.pbix"
    pbix_path.write_text("dummy")
    
    runner = CliRunner()
    res = runner.invoke(cli, ["check", str(pbix_path)])
    
    assert res.exit_code == 0
    assert "cannot parse .pbix files" in res.output
    assert "export to .pbit or PBIP" in res.output

