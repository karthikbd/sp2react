# Third-party code and notices

## In the sp2react package

sp2react **bundles no third-party code** and has no runtime dependencies. The parts that used to come from other
packages are written for sp2react on the Python standard library:

| Module | Replaces | Written from |
|---|---|---|
| `sp2react/transport.py` | requests | Python's `http.client` and `ssl` |
| `sp2react/ntlm.py` | requests-ntlm | Microsoft's MS-NLMP specification (NTLMv2, checked against its section 4.2.4 test vectors), RFC 1320 (MD4) and RFC 5929 (TLS channel bindings) |
| `sp2react/model.py` | pydantic | Python's `typing` |
| `sp2react/yamlish.py` | PyYAML | the YAML 1.2 specification (the subset used in configuration files) |

The optional extras (`mysql`, `mssql`, `db`) install SQLAlchemy and PyMySQL or pyodbc from PyPI under their own
licences (MIT, MIT, MIT); they are not part of the sp2react distribution.

## In the generated application

The React + FastAPI app that sp2react writes declares its own dependencies in `backend/requirements.txt` and
`frontend/package.json` (FastAPI, Uvicorn, SQLAlchemy, requests, React, React Router, Vite, TypeScript). They are
installed by whoever builds the generated app, under their own licences, and are not shipped in the sp2react wheel.
The code sp2react writes into that app is covered by sp2react's MIT licence.
