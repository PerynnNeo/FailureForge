"""Regenerate the browser's API input contract from the service schema."""
import json
import tempfile
from pathlib import Path

from failureforge.api import create_app

root = Path(__file__).resolve().parents[1]
(root / "tmp").mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(dir=root / "tmp") as scratch:
    schema = create_app(scratch).openapi()
(root / "docs" / "openapi.json").write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
print("Wrote docs/openapi.json")
