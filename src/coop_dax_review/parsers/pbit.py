import zipfile
import json
from coop_dax_review.model import ModelCatalog
from coop_dax_review.parsers.bim import build_catalog_from_dict

def parse_pbit_model(file: str) -> ModelCatalog:
    """Parse a .pbit zip file and extract the DataModelSchema JSON."""
    try:
        with zipfile.ZipFile(file, "r") as z:
            if "DataModelSchema" not in z.namelist():
                raise ValueError("DataModelSchema not found in .pbit archive")
            
            with z.open("DataModelSchema") as f:
                content = f.read()
                
            # UTF-16-LE is the standard for DataModelSchema in PBI templates
            try:
                # remove BOM if present
                if content.startswith(b'\xff\xfe'):
                    content = content[2:]
                text = content.decode("utf-16-le")
            except UnicodeDecodeError:
                # fallback to utf-8 just in case
                text = content.decode("utf-8-sig")
                
            data = json.loads(text)
            return build_catalog_from_dict(data, file)
    except zipfile.BadZipFile as e:
        raise ValueError(f"invalid zip archive: {e}") from e
