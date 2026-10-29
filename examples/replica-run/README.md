# Example run on the replica site

This is the output of `sp2react run --auto-approve` on `tests/fixtures/legacy-site` with scripted agents, followed by `tests/ui_walkthrough.py` (29/29 checks passed).

- `sp2react-work/specs/*.coverage.md`: the spec rule that carries each legacy jQuery behaviour
- `sp2react-work/inventory/*.json`: what the analyser found, with file:line references
- `converted-app/`: the generated React + FastAPI app (run instructions are in the main README)
- `screenshots/`: the converted forms and dashboard
