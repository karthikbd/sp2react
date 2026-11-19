"""Fuzz spec validation with JSON an agent could return: anything other than ValidationError is a bug."""
import json
import sys

import atheris

with atheris.instrument_imports():
    from sp2react.model import ValidationError
    from sp2react.spec.model import Spec


def TestOneInput(data: bytes) -> None:  # noqa: N802 (atheris naming)
    text = atheris.FuzzedDataProvider(data).ConsumeUnicodeNoSurrogates(len(data))
    try:
        doc = json.loads(text)
    except (ValueError, RecursionError):
        return
    try:
        spec = Spec.model_validate(doc)
    except ValidationError:
        return
    again = Spec.model_validate_json(spec.model_dump_json(exclude_none=True))   # a valid spec round-trips
    assert again.screen.id == spec.screen.id


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
