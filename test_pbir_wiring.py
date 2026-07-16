from pathlib import Path
import json

def get_report_dirs(catalog_file: str) -> list[Path]:
    catalog_path = Path(catalog_file)
    model_dir = catalog_path.parent if catalog_path.is_file() else catalog_path
    if not model_dir.name.endswith(".SemanticModel"):
        # For bare .bim files not in a PBIP structure, we might look in the same dir
        parent_dir = model_dir.parent
        basename = model_dir.stem
    else:
        parent_dir = model_dir.parent
        basename = model_dir.name[:-len(".SemanticModel")]
        
    report_dirs = []
    
    # Check for exact sibling <basename>.Report
    exact_report = parent_dir / f"{basename}.Report"
    if exact_report.is_dir():
        report_dirs.append(exact_report)
        
    return report_dirs

print(get_report_dirs("Project.SemanticModel/model.bim"))
