"""Fuzz what comes off the network: NTLM CHALLENGE messages and WWW-Authenticate headers from any server,
and $filter expressions sent to the generated API (its OData parser)."""
import importlib.util
import pathlib
import struct
import sys

import atheris

with atheris.instrument_imports():
    import sp2react
    from sp2react import ntlm

try:            # ClusterFuzzLite: build.sh copies the generated app's odata.py next to this file, so it is bundled
    with atheris.instrument_imports():
        import generated_odata as odata
except ImportError:   # run from a checkout: load it from the package's templates
    _spec = importlib.util.spec_from_file_location(
        "generated_odata", pathlib.Path(sp2react.__file__).parent / "scaffold" / "templates" / "backend" / "app" / "odata.py")
    odata = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(odata)
ITEMS = [{"ID": 1, "Title": "Kestrel", "Status": "Approved", "Country": {"id": 8, "title": "Nigeria"}, "Amount": 5.0}]


def TestOneInput(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    which = fdp.ConsumeIntInRange(0, 2)
    if which == 0:
        msg = fdp.ConsumeBytes(fdp.remaining_bytes())
        try:
            ntlm.authenticate_message(ntlm.SIGNATURE + struct.pack("<I", 2) + msg, "user", "pw", "DOM")
        except (ntlm.NTLMError, struct.error):
            pass
    elif which == 1:
        ntlm.header_token(fdp.ConsumeUnicodeNoSurrogates(fdp.remaining_bytes()))
    else:
        expr = fdp.ConsumeUnicodeNoSurrogates(fdp.remaining_bytes())
        try:
            odata.apply_query(ITEMS, expr)
        except (odata.ODataError, RecursionError):
            pass


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
