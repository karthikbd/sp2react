"""Rewrite an sdist so the same commit always produces the same bytes.

setuptools stamps the tarball with build-time modification times (directories, PKG-INFO, the
generated egg-info) and the gzip header with the current time. This keeps every file's content
and mode and fixes the rest: members in name order, every mtime = SOURCE_DATE_EPOCH, owner root:root
with no user/group names, and a gzip header with that time and no file name.

Usage: SOURCE_DATE_EPOCH=$(git log -1 --format=%ct) python ci/reproducible_sdist.py dist/*.tar.gz
"""
import gzip
import io
import os
import sys
import tarfile


def normalize(path: str, epoch: int) -> None:
    with tarfile.open(path, "r:gz") as src:
        members = sorted(src.getmembers(), key=lambda m: m.name)
        data = {m.name: src.extractfile(m).read() for m in members if m.isfile()}
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as out:
        for m in members:
            m.mtime = epoch
            m.uid = m.gid = 0
            m.uname = m.gname = ""
            m.pax_headers = {}
            m.mode = 0o755 if m.isdir() or m.mode & 0o111 else 0o644
            out.addfile(m, io.BytesIO(data[m.name]) if m.isfile() else None)
    with open(path, "wb") as f, gzip.GzipFile(filename="", mode="wb", fileobj=f, mtime=epoch, compresslevel=9) as gz:
        gz.write(raw.getvalue())


if __name__ == "__main__":
    epoch = int(os.environ["SOURCE_DATE_EPOCH"])
    for p in sys.argv[1:]:
        normalize(p, epoch)
        print("normalized", p)
