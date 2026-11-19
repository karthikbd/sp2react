"""Fuzz the legacy-code analysis: ASPX pages, web part markup and jQuery/SPServices JavaScript from any site."""
import sys

import atheris

with atheris.instrument_imports():
    from sp2react.analysis.aspx import parse_page, scan_html
    from sp2react.analysis.behaviors import FieldIndex, analyze_script


def TestOneInput(data: bytes) -> None:  # noqa: N802 (atheris naming)
    fdp = atheris.FuzzedDataProvider(data)
    which = fdp.ConsumeIntInRange(0, 2)
    text = fdp.ConsumeUnicodeNoSurrogates(fdp.remaining_bytes())
    if which == 0:
        parse_page("SitePages/Fuzz.aspx", text, None)
    elif which == 1:
        scan_html(text)
    else:
        analyze_script("fuzz.js", text, FieldIndex())


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
