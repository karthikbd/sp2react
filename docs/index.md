---
html_theme.sidebar_secondary.remove: true
---

# sp2react documentation

**Version**: {{ version }}

**Download**: [PyPI package](https://pypi.org/project/sp2react/)

**Useful links**:
[Installation](getting_started/install.md) |
[Walkthrough](getting_started/walkthrough.md) |
[Configuration](user_guide/configuration.md) |
[Your database](user_guide/database.md) |
[Troubleshooting](user_guide/troubleshooting.md) |
[Release notes](whatsnew/index.md)

**sp2react** is an open source, MIT-licensed Python package that converts a classic SharePoint site
(ASPX pages, list forms, jQuery and SPServices scripts) into a React + FastAPI application that reads
and writes your existing database. AI agents (Claude, through GitHub Copilot Bridger by default) handle
the parts that need judgement; plain code does the rest, and nothing an agent writes is accepted until
it passes automatic checks. It has no runtime dependencies, reads the site with GET requests only, and
never sends business data to the model.

::::::{grid} 1 2 2 2
:gutter: 4
:padding: 2 2 0 0
:class-container: sd-text-center

::::{grid-item-card} Getting started
:img-top: _static/index_getting_started.svg
:class-card: intro-card
:shadow: md

New to *sp2react*? How it works, installation (including corporate repositories), and a site
converted from start to finish.

:::{card-footer}
```{button-ref} getting_started/index
:ref-type: doc
:click-parent:
:color: secondary
:expand:

To the getting started guides
```
:::
::::

::::{grid-item-card} User guide
:img-top: _static/index_user_guide.svg
:class-card: intro-card
:shadow: md

Configuration, the model provider, your database, the generated app, security, troubleshooting and
what is and is not converted.

:::{card-footer}
```{button-ref} user_guide/index
:ref-type: doc
:click-parent:
:color: secondary
:expand:

To the user guide
```
:::
::::

::::{grid-item-card} Reference
:img-top: _static/index_api.svg
:class-card: intro-card
:shadow: md

Every command, option and file written, and the Python API for driving sp2react from your own
tools.

:::{card-footer}
```{button-ref} reference/index
:ref-type: doc
:click-parent:
:color: secondary
:expand:

To the reference
```
:::
::::

::::{grid-item-card} Developer guide
:img-top: _static/index_contribute.svg
:class-card: intro-card
:shadow: md

The architecture, the security assurance case, the dependency policy, the test layers and
releasing to PyPI.

:::{card-footer}
```{button-ref} development/index
:ref-type: doc
:click-parent:
:color: secondary
:expand:

To the development guide
```
:::
::::

::::::

```{toctree}
:maxdepth: 3
:hidden:
:titlesonly:

getting_started/index
user_guide/index
reference/index
development/index
whatsnew/index
changelog
```
