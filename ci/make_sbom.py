"""Write a CycloneDX 1.5 SBOM for the built package.

sp2react has no runtime dependencies and bundles no third-party code: its HTTP client, NTLM sign-in, YAML reader
and validation are written for the package on the Python standard library. The SBOM states exactly that, and lists
the optional extras, so JFrog Xray / Curation, Dependency-Track and similar tools see the whole picture.

    python ci/make_sbom.py sbom/sp2react.cdx.json
"""
import datetime
import json
import sys
import tomllib
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
meta = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
name, version = meta["name"], meta["version"]
ref = f"pkg:pypi/{name}@{version}"
extras = {k: v for k, v in meta.get("optional-dependencies", {}).items() if k != "dev"}

sbom = {
    "bomFormat": "CycloneDX",
    "specVersion": "1.5",
    "serialNumber": f"urn:uuid:{uuid.uuid4()}",
    "version": 1,
    "metadata": {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "component": {
            "type": "library", "bom-ref": ref, "name": name, "version": version, "purl": ref,
            "licenses": [{"license": {"id": "MIT"}}],
            "externalReferences": [{"type": "vcs", "url": "https://github.com/karthikbd/sp2react"}],
            "properties": [
                {"name": "sp2react:runtime-dependencies", "value": "none"},
                {"name": "sp2react:bundled-third-party-code", "value": "none"},
            ] + [{"name": f"sp2react:optional-extra:{k}", "value": ", ".join(v) or "(empty)"} for k, v in extras.items()],
        },
    },
    "components": [],
    "dependencies": [{"ref": ref, "dependsOn": []}],
}
out = Path(sys.argv[1] if len(sys.argv) > 1 else f"dist/{name}-{version}.cdx.json")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(sbom, indent=2), encoding="utf-8")
print(f"wrote {out}")
