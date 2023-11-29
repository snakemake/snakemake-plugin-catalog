# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = "Snakemake plugin catalog"
copyright = "2023, The Snakemake team"
author = "Johannes Köster"

import sys

sys.path.insert(0, ".")
from collect_plugins import collect_plugins

collect_plugins()

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = []

templates_path = ["_templates"]
exclude_patterns = []


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "lutra"
html_static_path = ["_static"]
# html_css_files = ["theme.css"]
html_theme_options = {
    "primary_color": "emerald",
    "secondary_color": "emerald",
    "dark_logo": "logo-snake.svg",
    "light_logo": "logo-snake.svg",
    "navigation_style": "plain",
    "sidebar_links": [
        {"text": "Snakemake documentation", "alt": "Snakemake documentation", "href": "https://snakemake.readthedocs.io"},
    ]
}
html_title = "Snakemake plugin catalog"
