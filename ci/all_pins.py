"""Write every version pinned in a hash-locked requirements file, whatever its environment marker.

`pip-audit -r ci/requirements-x.txt` only audits the pins whose markers match the interpreter it runs on,
so a version pinned only for another Python (``; python_full_version < '3.11'``) would never be checked.
This splits the pins into files with one version per package (marker dropped) so each can be audited.

Usage: python ci/all_pins.py ci/requirements-test.txt OUTDIR  -> OUTDIR/requirements-test.0.txt, .1.txt ...
"""
import re
import sys
from pathlib import Path

PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)", re.M)


def split(path: Path, outdir: Path) -> list[Path]:
    groups: list[dict[str, str]] = []
    for name, version in PIN.findall(path.read_text(encoding="utf-8")):
        key = name.lower().replace("_", "-")
        for g in groups:
            if key not in g:
                g[key] = version
                break
        else:
            groups.append({key: version})
    outdir.mkdir(parents=True, exist_ok=True)
    files = []
    for i, g in enumerate(groups):
        f = outdir / f"{path.stem}.{i}.txt"
        f.write_text("".join(f"{n}=={v}\n" for n, v in sorted(g.items())), encoding="utf-8")
        files.append(f)
    return files


if __name__ == "__main__":
    for f in split(Path(sys.argv[1]), Path(sys.argv[2])):
        print(f)
