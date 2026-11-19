# Development

```{toctree}
:maxdepth: 2

architecture
security-assurance
dependencies
testing
releasing
```

```console
$ git clone https://github.com/karthikbd/sp2react && cd sp2react
$ python -m venv .venv && . .venv/bin/activate
$ pip install --require-hashes -r ci/requirements-test.txt   # test tools and the generated app's packages
$ pip install --no-deps -e .
$ pytest -q                                   # unit, pipeline, generated-app and over-the-wire HTTP tests
$ python -m sphinx -W -b html docs docs/_build/html   # this documentation, warnings are errors
```

## Project

- [Governance](https://github.com/karthikbd/sp2react/blob/main/GOVERNANCE.md): roles, decisions, who holds which keys, continuity.
- [Roadmap](https://github.com/karthikbd/sp2react/blob/main/ROADMAP.md): plans for the next 12 months.
- [Contributing](https://github.com/karthikbd/sp2react/blob/main/CONTRIBUTING.md): how to propose a change, review standards, DCO.
- [Code of Conduct](https://github.com/karthikbd/sp2react/blob/main/CODE_OF_CONDUCT.md).
- [Security policy](https://github.com/karthikbd/sp2react/blob/main/SECURITY.md): reporting, response, supported versions.
