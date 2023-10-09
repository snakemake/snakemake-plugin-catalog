from collections import defaultdict
from pathlib import Path
import shutil

import requests
from ratelimit import limits, sleep_and_retry
from jinja2 import Environment, FileSystemLoader, select_autoescape


@sleep_and_retry
@limits(calls=20, period=1)
def pypi_api(query, accept="application/json"):
    return requests.get(
        query,
        headers={
            "Accept": accept,
            "User-Agent": "Snakemake plugin catalog (https://github.com/snakemake/snakemake-plugin-catalog)",
        },
    ).json()


def collect_plugins():

    templates = Environment(
        loader=FileSystemLoader("_templates"), autoescape=select_autoescape()
    )

    data = pypi_api(
        "https://pypi.org/simple/", accept="application/vnd.pypi.simple.v1+json"
    )

    plugins = defaultdict(list)

    for plugin_type in ("executor", "storage"):
        plugin_dir = Path("plugins") / plugin_type
        shutil.rmtree(plugin_dir)
        plugin_dir.mkdir(parents=True, exist_ok=True)
        prefix = f"snakemake-{plugin_type}-plugin-"
        packages = [
            project["name"]
            for project in data["projects"]
            if project["name"].startswith(prefix)
        ]
        for package in packages:
            meta = pypi_api(f"https://pypi.org/pypi/{package}/json")
            plugin_name = package.removeprefix(prefix)
            desc = "\n".join(meta["info"]["description"].split("\n")[2:])
            # TODO use meta in template to display more information
            rendered = templates.get_template(f"{plugin_type}_plugin.rst.j2").render(
                plugin_name=plugin_name,
                package_name=package,
                meta=meta,
                desc=desc,
                plugin_type=plugin_type,
            )
            with open((plugin_dir / plugin_name).with_suffix(".rst"), "w") as f:
                f.write(rendered)
            plugins[plugin_type].append(plugin_name)

    with open("index.rst", "w") as f:
        f.write(templates.get_template("index.rst.j2").render(plugins=plugins))
