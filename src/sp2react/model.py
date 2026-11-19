"""Typed records validated from plain data (JSON, YAML), using only the standard library.

A small replacement for the parts of pydantic sp2react used: class annotations declare the fields, values are
checked and converted when a record is built from a dict, errors carry a location so an agent (or a person
editing the config) can be told exactly what to fix, and records dump back to JSON in field order.
"""
from __future__ import annotations

import json
import typing
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple, Union, get_args, get_origin

_MISSING = object()


class ValidationError(ValueError):
    """Raised with every problem found; errors() lists them as {"loc": (...), "msg": str, "type": str}."""

    def __init__(self, model: str, errors: List[dict]):
        self.model = model
        self._errors = errors
        lines = [f"{len(errors)} validation error{'s' if len(errors) != 1 else ''} for {model}"]
        for e in errors:
            lines.append(f"{'.'.join(str(x) for x in e['loc']) or '(root)'}\n  {e['msg']}")
        super().__init__("\n".join(lines))

    def errors(self) -> List[dict]:
        return list(self._errors)


class FieldInfo:
    __slots__ = ("default", "default_factory", "description")

    def __init__(self, default: Any = _MISSING, default_factory: Optional[Callable[[], Any]] = None, description: str = ""):
        self.default = default
        self.default_factory = default_factory
        self.description = description

    def make_default(self) -> Any:
        if self.default_factory is not None:
            return self.default_factory()
        return self.default


def Field(default: Any = _MISSING, *, default_factory: Optional[Callable[[], Any]] = None, description: str = "") -> Any:  # noqa: N802
    """Field(...) = required; Field(default_factory=list); Field("x", description=...)."""
    return FieldInfo(_MISSING if default is Ellipsis else default, default_factory, description)


def field_validator(*names: str):
    """Decorates a classmethod that receives the converted value and returns the value to store."""
    def wrap(fn):
        func = fn.__func__ if isinstance(fn, classmethod) else fn
        func.__validates__ = names
        return classmethod(func)
    return wrap


class _Problems:
    def __init__(self) -> None:
        self.errors: List[dict] = []

    def add(self, loc: Tuple, msg: str, kind: str) -> None:
        if len(self.errors) < 200:
            self.errors.append({"loc": loc, "msg": msg, "type": kind})


def _type_name(tp: Any) -> str:
    return getattr(tp, "__name__", None) or str(tp).replace("typing.", "")


def _convert(tp: Any, value: Any, loc: Tuple, probs: _Problems) -> Any:
    """Check `value` against the annotation `tp`; return the converted value (or _MISSING after recording a problem)."""
    if tp is Any or tp is object:
        return value
    origin = get_origin(tp)
    if origin is Union:
        args = get_args(tp)
        if value is None and type(None) in args:
            return None
        inner = _Problems()
        for a in (x for x in args if x is not type(None)):
            trial = _Problems()
            out = _convert(a, value, loc, trial)
            if not trial.errors:
                return out
            inner.errors += trial.errors
        if len(args) == 2 and type(None) in args:       # Optional[X]: report X's own message
            probs.errors += inner.errors[:5]
        else:
            probs.add(loc, f"Input should be one of: {', '.join(_type_name(a) for a in args)}", "union")
        return _MISSING
    if origin is Literal:
        allowed = get_args(tp)
        if value in allowed and not (isinstance(value, bool) and not any(isinstance(a, bool) for a in allowed)):
            return value
        probs.add(loc, f"Input should be {' or '.join(repr(a) for a in allowed)}", "literal_error")
        return _MISSING
    if origin in (list, List):
        (item,) = get_args(tp) or (Any,)
        if not isinstance(value, (list, tuple)):
            probs.add(loc, "Input should be a valid list", "list_type")
            return _MISSING
        out = [_convert(item, v, loc + (i,), probs) for i, v in enumerate(value)]
        return out
    if origin in (dict, Dict):
        kt, vt = get_args(tp) or (Any, Any)
        if not isinstance(value, dict):
            probs.add(loc, "Input should be a valid dictionary", "dict_type")
            return _MISSING
        return {_convert(kt, k, loc + (k,), probs): _convert(vt, v, loc + (k,), probs) for k, v in value.items()}
    if origin in (tuple, Tuple):
        args = get_args(tp)
        if not isinstance(value, (list, tuple)):
            probs.add(loc, "Input should be a valid tuple", "tuple_type")
            return _MISSING
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(_convert(args[0], v, loc + (i,), probs) for i, v in enumerate(value))
        return tuple(_convert(a, v, loc + (i,), probs) for i, (a, v) in enumerate(zip(args, value)))
    if isinstance(tp, type) and issubclass(tp, BaseModel):
        if isinstance(value, tp):
            return value
        if not isinstance(value, dict):
            probs.add(loc, f"Input should be a valid dictionary or instance of {tp.__name__}", "model_type")
            return _MISSING
        return tp._build(value, loc, probs)
    if tp is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, int) and value in (0, 1):
            return bool(value)
        if isinstance(value, str) and value.strip().lower() in ("true", "false", "yes", "no", "on", "off", "1", "0"):
            return value.strip().lower() in ("true", "yes", "on", "1")
        probs.add(loc, "Input should be a valid boolean", "bool_type")
        return _MISSING
    if tp is int:
        if isinstance(value, bool):
            probs.add(loc, "Input should be a valid integer", "int_type")
            return _MISSING
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str) and value.strip().lstrip("+-").isdigit():
            return int(value.strip())
        probs.add(loc, "Input should be a valid integer", "int_type")
        return _MISSING
    if tp is float:
        if isinstance(value, bool):
            probs.add(loc, "Input should be a valid number", "float_type")
            return _MISSING
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                pass
        probs.add(loc, "Input should be a valid number", "float_type")
        return _MISSING
    if tp is str:
        if isinstance(value, str):
            return value
        probs.add(loc, "Input should be a valid string", "string_type")
        return _MISSING
    if isinstance(tp, type):
        if isinstance(value, tp):
            return value
        probs.add(loc, f"Input should be an instance of {tp.__name__}", "is_instance_of")
        return _MISSING
    return value


def _dump(value: Any, exclude_none: bool) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(exclude_none=exclude_none)
    if isinstance(value, dict):
        return {k: _dump(v, exclude_none) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_dump(v, exclude_none) for v in value]
    return value


class BaseModel:
    """Declare fields as class annotations, with defaults or Field(...). Unknown input keys are ignored."""

    __fields__: Dict[str, Tuple[Any, "FieldInfo"]] = {}    # name -> (annotation, FieldInfo), filled on first use
    __validators__: Dict[str, List[Any]] = {}              # name -> [classmethod functions]
    __resolved__ = False

    def __init_subclass__(cls, **kw):
        super().__init_subclass__(**kw)
        cls.__resolved__ = False

    @classmethod
    def _resolve(cls) -> None:
        if cls.__dict__.get("__resolved__"):
            return
        own = {n for k in cls.__mro__ for n in k.__dict__.get("__annotations__", {})}
        local = {k: v for k, v in vars(cls).items() if k not in own}      # a field named `list` must not hide list[...]
        hints = typing.get_type_hints(cls, localns=local)                 # each class's annotations in its own module
        fields: Dict[str, Tuple[Any, FieldInfo]] = {}
        for klass in reversed(cls.__mro__):
            for name in klass.__dict__.get("__annotations__", {}):
                if name.startswith("_") or name not in hints:
                    continue
                raw = getattr(cls, name, _MISSING)
                info = raw if isinstance(raw, FieldInfo) else FieldInfo(raw)
                fields[name] = (hints[name], info)
        validators: Dict[str, List[Any]] = {}
        for klass in reversed(cls.__mro__):
            for attr in klass.__dict__.values():
                func = attr.__func__ if isinstance(attr, classmethod) else None
                for name in getattr(func, "__validates__", ()):
                    validators.setdefault(name, []).append(func)
        cls.__fields__, cls.__validators__ = fields, validators
        cls.__resolved__ = True

    @classmethod
    def _build(cls, data: dict, loc: Tuple, probs: _Problems):
        cls._resolve()
        obj = cls.__new__(cls)
        for name, (tp, info) in cls.__fields__.items():
            if name in data:
                start = len(probs.errors)
                value = _convert(tp, data[name], loc + (name,), probs)
                if value is not _MISSING and len(probs.errors) == start:
                    for v in cls.__validators__.get(name, []):
                        try:
                            value = v(cls, value)
                        except (ValueError, TypeError, AssertionError) as e:
                            probs.add(loc + (name,), f"Value error, {e}", "value_error")
            else:
                value = info.make_default()
                if value is _MISSING:
                    probs.add(loc + (name,), "Field required", "missing")
            object.__setattr__(obj, name, value)
        return obj

    def __init__(self, **data: Any):
        built = type(self).model_validate(data)
        self.__dict__.update(built.__dict__)

    @classmethod
    def model_validate(cls, data: Any):
        if isinstance(data, cls):
            return data
        probs = _Problems()
        if not isinstance(data, dict):
            raise ValidationError(cls.__name__, [{"loc": (), "msg": "Input should be a valid dictionary", "type": "dict_type"}])
        obj = cls._build(data, (), probs)
        if probs.errors:
            raise ValidationError(cls.__name__, probs.errors)
        return obj

    @classmethod
    def model_validate_json(cls, text: str):
        try:
            data = json.loads(text)
        except ValueError as e:
            raise ValidationError(cls.__name__, [{"loc": (), "msg": f"Invalid JSON: {e}", "type": "json_invalid"}]) from e
        return cls.model_validate(data)

    def model_dump(self, exclude_none: bool = False) -> dict:
        type(self)._resolve()
        out = {}
        for name in type(self).__fields__:
            v = getattr(self, name)
            if exclude_none and v is None:
                continue
            out[name] = _dump(v, exclude_none)
        return out

    def model_dump_json(self, indent: Optional[int] = None, exclude_none: bool = False) -> str:
        return json.dumps(self.model_dump(exclude_none=exclude_none), indent=indent, ensure_ascii=False,
                          separators=(",", ":") if indent is None else None)

    def __eq__(self, other: Any) -> bool:
        return type(other) is type(self) and self.model_dump() == other.model_dump()

    def __repr__(self) -> str:
        type(self)._resolve()
        body = ", ".join(f"{k}={getattr(self, k)!r}" for k in type(self).__fields__)
        return f"{type(self).__name__}({body})"
