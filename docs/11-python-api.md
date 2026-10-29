# 11. Python API

Everything the command line does is available from Python, for example to drive sp2react from your own migration tool (such as a "cockpit" UI) and show stage status there.

## Run everything

```python
from sp2react import Pipeline, load_config

p = Pipeline(load_config("sp2react.yaml"), progress=print)
state = p.run(until="spec")            # stops at the spec approval gate
```

`run(pages=None, offline=False, until="approve")` behaves exactly like `sp2react run`.

## Stage by stage

```python
from sp2react import Pipeline, load_config

p = Pipeline(load_config("sp2react.yaml"), progress=lambda msg: print("[sp2react]", msg))

p.stage_inputs(offline=False)
p.stage_extract(pages=None, offline=False)                 # or a list of page URLs
screens = [s["id"] for s in p.stage_inventory(None)]
p.stage_spec(screens)

# ... show specs/<id>.coverage.md to a reviewer, then:
p.approve("VendorRequests-form", "spec", by="reviewer@corp")

p.stage_map_db([p.load_spec(s) for s in p.approved_sids()])
p.stage_convert(screens)       # only approved screens are converted
p.stage_review(screens)
p.stage_test_and_fix(screens)

p.approve("VendorRequests-form", "screen", by="reviewer@corp")
```

## Reading status

```python
p.status("VendorRequests-form", "spec")      # 'done', 'failed', 'running', 'waiting', 'skipped', 'warning' or None
p.status(None, "map_db")                     # site-wide stages use None
p.state                                      # the whole state (also in sp2react-work/state.json)
p.screens()                                  # screens found by the inventory
p.load_spec("Dashboard")                     # the Spec model
p.load_inventory("Dashboard")                # behaviours and data calls
p.approvals()                                # who approved what
```

Each entry in `p.state["screens"][screen][stage]` has `status`, `detail` (the human explanation) and a timestamp. `p.state["usage"]` holds model tokens, attempts and seconds per screen and stage.

```python
from sp2react.pipeline import write_report
write_report(p)                               # refresh sp2react-work/report.md
```

## Constructor

```python
Pipeline(cfg, llm=None, progress=print, sp_client=None)
```

| Argument | Meaning |
|---|---|
| `cfg` | a `Config`, usually from `load_config(path)` |
| `llm` | optional model client; by default it is built from `cfg.llm` |
| `progress` | callable receiving one-line progress messages (called from worker threads, serialised by sp2react) |
| `sp_client` | optional SharePoint client, e.g. for testing |

## Errors

| Exception | Raised when |
|---|---|
| `sp2react.config.ConfigError` | the config is missing or invalid, or a required environment variable is not set |
| `sp2react.pipeline.StageBlocked` | a stage was called before the stage it depends on is done (stages normally record this as a status rather than raising) |
| `sp2react.net.NetworkPolicyError` | a request to a host that is not allowed |

Stage methods record failures in the state rather than raising, so a UI can show them; check `p.status(...)` after each call.
