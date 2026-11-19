"""Sphinx configuration for the sp2react documentation (Read the Docs: https://sp2react.readthedocs.io)."""
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "src"))

import sp2react  # noqa: E402

project = "sp2react"
author = "Karthikeyan Balasundaram"
copyright = "2026, Karthikeyan Balasundaram"
release = sp2react.__version__
version = ".".join(release.split(".")[:2])

extensions = ["myst_parser", "sphinx_copybutton"]
myst_enable_extensions = ["colon_fence", "deflist"]
myst_heading_anchors = 3
source_suffix = {".md": "markdown"}
root_doc = "index"
exclude_patterns = ["_build", "README.md"]
suppress_warnings = ["myst.header"]
copybutton_prompt_text = r"\$ |>>> |PS> "
copybutton_prompt_is_regexp = True

html_theme = "pydata_sphinx_theme"
html_title = f"sp2react {release}"
html_show_sourcelink = False
html_copy_source = False
html_theme_options = {
    "logo": {"text": "sp2react"},
    "navbar_align": "left",
    "show_toc_level": 2,
    "navigation_with_keys": False,
    "secondary_sidebar_items": ["page-toc"],
    "icon_links": [{"name": "PyPI", "url": "https://pypi.org/project/sp2react/", "icon": "fa-solid fa-box"},
                   {"name": "GitHub", "url": "https://github.com/karthikbd/sp2react", "icon": "fa-brands fa-github"}],
}
html_context = {"default_mode": "light"}
