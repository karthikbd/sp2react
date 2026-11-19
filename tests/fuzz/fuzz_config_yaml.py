"""Fuzz the config file reader: YAML text -> safe_load -> Config validation. Only YAMLError / ValidationError may escape."""
import sys

import atheris

with atheris.instrument_imports():
    from sp2react.config import Config
    from sp2react.model import ValidationError
    from sp2react.yamlish import YAMLError, safe_load


def TestOneInput(data: bytes) -> None:  # noqa: N802 (atheris naming)
    text = atheris.FuzzedDataProvider(data).ConsumeUnicodeNoSurrogates(len(data))
    try:
        doc = safe_load(text)
    except (YAMLError, RecursionError):
        return
    assert doc is None or isinstance(doc, (dict, list, str, int, float, bool))
    if isinstance(doc, dict):
        try:
            Config.model_validate(doc)
        except ValidationError:
            pass


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
