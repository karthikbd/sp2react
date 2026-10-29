"""sp2react: convert classic SharePoint ASPX/jQuery list forms and pages into React + FastAPI with AI agents.

Python API:
    from sp2react import Pipeline, load_config
    p = Pipeline(load_config("sp2react.yaml"))
    p.run(pages=["SitePages/Dashboard.aspx"])
"""
__version__ = "0.1.0"


def __getattr__(name):
    if name == "Pipeline":
        from .pipeline import Pipeline
        return Pipeline
    if name == "load_config":
        from .config import load_config
        return load_config
    raise AttributeError(name)
