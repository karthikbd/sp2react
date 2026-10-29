"""The screen spec: the single contract between analysis, agents, code generation and the runtime.

The generated app interprets rules at runtime (same engine in TypeScript and Python), so a rule
written once is enforced in the browser and again on the server.
"""
from __future__ import annotations

import builtins
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

Mode = Literal["new", "edit", "display"]

RULE_KINDS = (
    "visible", "required", "readonly", "default", "derive", "cascade", "compare", "length", "range", "pattern",
    "unique", "set_on_save", "lock_item", "on_save", "banner", "confirm", "navigate", "custom",
)

# params each rule kind must carry
RULE_PARAMS: Dict[str, tuple[str, ...]] = {
    "default": ("value",),
    "derive": ("from_field", "column"),
    "cascade": ("parent", "via"),
    "compare": ("op", "other"),
    "length": ("op", "value"),
    "range": ("op", "value"),
    "pattern": ("regex",),
    "set_on_save": ("value",),
    "on_save": ("action",),
    "navigate": ("to",),
    "custom": ("handler", "description"),
}
NEEDS_FIELD = {"visible", "required", "readonly", "default", "derive", "cascade", "compare", "length", "range", "pattern", "unique", "set_on_save"}
NEEDS_MESSAGE = {"compare", "length", "range", "pattern", "unique", "lock_item", "banner", "confirm"}


class Rule(BaseModel):
    id: str
    kind: Literal[RULE_KINDS]  # type: ignore[valid-type]
    field: Optional[str] = None
    list: Optional[str] = None                     # defaults to the screen's primary list
    modes: List[Mode] = Field(default_factory=builtins.list)  # empty = every mode
    when: Optional[Dict[str, Any]] = None
    message: Optional[str] = None                  # verbatim legacy text; {field} placeholders allowed
    presentation: Literal["inline", "alert", "banner", "confirm"] = "inline"
    params: Dict[str, Any] = Field(default_factory=builtins.dict)
    covers: List[str] = Field(default_factory=builtins.list)
    src: List[str] = Field(default_factory=builtins.list)   # "file:line" references into the legacy source
    origin: Literal["schema", "inventory", "agent"] = "agent"
    note: Optional[str] = None


class Endpoint(BaseModel):
    id: str
    method: Literal["GET", "POST", "PATCH", "DELETE"]
    path: str
    purpose: str
    list: Optional[str] = None
    query: Dict[str, Any] = Field(default_factory=builtins.dict)   # filter/select/expand/orderby/top in the API's OData subset
    body: List[str] = Field(default_factory=builtins.list)
    roles: List[str] = Field(default_factory=builtins.list)        # SharePoint group names allowed; empty = any signed-in user
    custom: bool = False                                  # needs an agent-written handler (not the generic list API)
    covers: List[str] = Field(default_factory=builtins.list)
    src: List[str] = Field(default_factory=builtins.list)


class Component(BaseModel):
    id: str
    kind: Literal["form", "tiles", "table", "list_view", "banner", "html", "actions", "custom"]
    title: Optional[str] = None
    region: Optional[str] = None                   # zone / column, to keep the legacy layout
    order: int = 0
    data: List[str] = Field(default_factory=builtins.list)  # endpoint ids this component reads/writes
    props: Dict[str, Any] = Field(default_factory=builtins.dict)
    roles: List[str] = Field(default_factory=builtins.list) # visible only to these SharePoint groups
    covers: List[str] = Field(default_factory=builtins.list)
    src: List[str] = Field(default_factory=builtins.list)


class Screen(BaseModel):
    id: str
    kind: Literal["list-form", "page"]
    title: str
    route: str
    legacy_urls: List[str] = Field(default_factory=builtins.list)
    list: Optional[str] = None
    modes: List[Mode] = Field(default_factory=builtins.list)
    components: List[Component] = Field(default_factory=builtins.list)
    stylesheets: List[str] = Field(default_factory=builtins.list)
    covers: List[str] = Field(default_factory=builtins.list)


class ListSpec(BaseModel):
    title: str
    primary: bool = False
    fields: List[Dict[str, Any]]
    attachments: bool = False
    views: Dict[str, Any] = Field(default_factory=builtins.dict)


class NotCarried(BaseModel):
    covers: List[str]
    reason: str


class Spec(BaseModel):
    version: int = 1
    screen: Screen
    lists: Dict[str, ListSpec]
    rules: List[Rule] = Field(default_factory=builtins.list)
    endpoints: List[Endpoint] = Field(default_factory=builtins.list)
    roles: List[str] = Field(default_factory=builtins.list)       # SharePoint groups the screen checks
    not_carried: List[NotCarried] = Field(default_factory=builtins.list)
    open_questions: List[str] = Field(default_factory=builtins.list)

    def all_covers(self) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {}
        for r in self.rules:
            for c in r.covers:
                out.setdefault(c, []).append(f"rule:{r.id}")
        for e in self.endpoints:
            for c in e.covers:
                out.setdefault(c, []).append(f"endpoint:{e.id}")
        for comp in self.screen.components:
            for c in comp.covers:
                out.setdefault(c, []).append(f"component:{comp.id}")
        for c in self.screen.covers:
            out.setdefault(c, []).append("screen")
        for n in self.not_carried:
            for c in n.covers:
                out.setdefault(c, []).append("not_carried")
        return out
