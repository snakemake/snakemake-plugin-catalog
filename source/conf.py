# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

import sys
from sphinxawesome_theme.postprocess import Icons

sys.path.insert(0, ".")
from collect_plugins import collect_plugins

collect_plugins()

project = "Snakemake plugin catalog"
copyright = "2023, The Snakemake team"
author = "Johannes Köster"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = []

templates_path = ["_templates"]
exclude_patterns = []


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "sphinxawesome_theme"
html_static_path = ["_static"]
html_css_files = ["custom.css"]
html_theme_options = {
    "logo_light": "_static/logo-snake.svg",
    "logo_dark": "_static/logo-snake.svg",
    "main_nav_links": {
        "Snakemake homepage": "https://snakemake.github.io",
        "Snakemake documentation": "https://snakemake.readthedocs.io",
    },
}
html_title = "Snakemake plugin catalog"
html_css_files = ["custom.css"]
html_permalinks_icon = Icons.permalinks_icon
