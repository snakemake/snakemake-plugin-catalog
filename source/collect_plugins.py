from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap
from typing import Any, Dict, List, Optional
import uuid
from pypi_simple import PyPISimple

import requests
from ratelimit import limits, sleep_and_retry
from jinja2 import Environment, FileSystemLoader, select_autoescape
import m2r2


TEST_PACKAGES = os.environ.get("TEST_PACKAGES").split(",") if "TEST_PACKAGES" in os.environ else None


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


class MetadataError(Exception):
    pass


class MetadataCollector:
    def __init__(self, package: str, plugin_type: str):
        self.envname = uuid.uuid4().hex
        self.package = package
        self.plugin_type = plugin_type

    def __enter__(self):
        py_ver = sys.version_info
        error = None
        for py_minor in range(py_ver.minor, 0, -1):
            py_ver_constraint = f"{py_ver.major}.{py_minor}"
            subprocess.run(
                f"micromamba create -n {self.envname} -y python={py_ver_constraint} pip",
                check=True,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                subprocess.run(
                    f"micromamba run -n {self.envname} pip install snakemake {self.package}",
                    shell=True,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            except subprocess.CalledProcessError as e:
                subprocess.run("micromamba env remove -n {self.envname} -y", shell=True)
                if error is None:
                    error = e.stderr.decode()
                print(
                    f"Error installing {self.package} with Python {py_ver_constraint}: {e.stderr.decode()}",
                    file=sys.stderr,
                )
            return self
        if error is not None:
            raise MetadataError(
                f"Cannot be installed with latest stable snakemake: {error}"
            )

    def __exit__(self, exc_type, exc_value, traceback):
        subprocess.run(
            f"micromamba env remove -n {self.envname} -y",
            check=True,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def extract_info(self, statement: str) -> str:
        registry = f"{self.plugin_type.title()}PluginRegistry"
        plugin_name = self.package.removeprefix(f"snakemake-{self.plugin_type}-plugin-")
        try:
            res = subprocess.run(
                f"micromamba run -n {self.envname} python -c \"from snakemake_interface_{self.plugin_type}_plugins.registry import {registry}; plugin = {registry}().get_plugin('{plugin_name}'); {statement}\"",
                shell=True,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except subprocess.CalledProcessError as e:
            raise MetadataError(f"Not a valid plugin: {e.stderr.decode()}") from e
        return res.stdout.decode()

    def get_settings(self) -> List[Dict[str, Any]]:
        info = self.extract_info(
            "import json; "
            "fmt_type = lambda thetype: thetype.__name__ if thetype is not None else None; "
            "fmt_setting_item = lambda key, value: (key, fmt_type(value)) if key == 'type' else (key, value); "
            "fmt_setting = lambda setting: dict(map(lambda item: fmt_setting_item(*item), setting.items())); "
            "print(json.dumps(list(map(fmt_setting, plugin.get_settings_info()))))"
        )
        return json.loads(info)


class PluginCollectorBase(ABC):
    @abstractmethod
    def plugin_type(self) -> str:
        raise NotImplementedError()

    def aux_info(self, metadata_collector) -> Dict[str, Any]:
        return {}

    def collect_plugins(self, plugins, packages, templates):
        plugin_type = self.plugin_type()
        plugin_dir = Path("plugins") / plugin_type
        if plugin_dir.exists():
            shutil.rmtree(plugin_dir)
        plugin_dir.mkdir(parents=True, exist_ok=True)
        prefix = f"snakemake-{plugin_type}-plugin-"
        packages = [package for package in packages if package.startswith(prefix)]
        for package in packages:
            if TEST_PACKAGES is not None and package not in TEST_PACKAGES:
                continue

            print("Collecting", package, file=sys.stderr)
            meta = pypi_api(f"https://pypi.org/pypi/{package}/json")
            plugin_name = package.removeprefix(prefix)
            desc = "\n".join(meta["info"]["description"].split("\n")[2:])

            # convert to rst
            desc = m2r2.convert(desc)

            error = None
            repository = None

            def get_setting_meta(setting, key, default="", verb=False):
                value = setting.get(key, default)
                if verb:
                    return f"``{repr(value)}``"
                elif isinstance(value, list):
                    return ", ".join(value)
                elif isinstance(value, bool):
                    return "✓" if value else "✗"
                elif value is None:
                    return default
                return value

            docs_warning = ""
            project_urls = meta.get("info", dict()).get("project_urls") or dict()
            repository = project_urls.get("Repository")
            repository_type = None
            if repository is None:
                docs_warning = (
                    "No repository URL found in Pypi metadata. The plugin should "
                    "specify a repository URL in its pyproject.toml (key 'repository'). "
                    "It is unclear whether the plugin is maintained and reviewed by "
                    "the official Snakemake organization (https://github.com/snakemake)."
                )
            else:
                if repository.startswith("https://github.com"):
                    repository_type = "github"
                elif repository.startswith("https://gitlab.com"):
                    repository_type = "gitlab"
            docs_intro = get_docs(repository, section="intro")
            docs_further = get_docs(repository, section="further")
            if repository is not None and docs_intro is None and docs_further is None:
                docs_warning = (
                    f"No documentation found in repository {repository}. The plugin should "
                    "provide a docs/intro.md with some introductory sentences and "
                    "optionally a docs/further.md file with details beyond the "
                    "auto-generated usage instructions presented in this catalog."
                )

            settings = {}
            aux_info = {}

            try:
                with MetadataCollector(package, plugin_type) as collector:
                    settings = collector.get_settings()
                    aux_info = self.aux_info(collector)
            except MetadataError as e:
                error = str(e)
                print(
                    f"Error installing {package} or retrieving metadata: {error}",
                    file=sys.stderr,
                )

            if error is not None:
                if repository is not None:
                    error += f"\n\nPlease file a corresponding issue in the plugin's `repository <{repository}>`__ (if there is none yet)."
                else:
                    error += "\n\nPlease contact the plugin author."

            rendered = templates.get_template(
                f"{plugin_type}_plugin.rst.j2"
            ).render(
                plugin_name=plugin_name,
                package_name=package,
                repository=repository,
                repository_type=repository_type,
                meta=meta,
                desc=desc,
                docs_intro=docs_intro,
                docs_further=docs_further,
                docs_warning=docs_warning,
                plugin_type=plugin_type,
                settings=settings,
                get_setting_meta=get_setting_meta,
                error=error,
                textwrap=textwrap,
                **aux_info,
            )
            with open((plugin_dir / plugin_name).with_suffix(".rst"), "w") as f:
                f.write(rendered)

            plugins[plugin_type].append(plugin_name)


class ExecutorPluginCollector(PluginCollectorBase):
    def plugin_type(self) -> str:
        return "executor"


class ReportPluginCollector(PluginCollectorBase):
    def plugin_type(self) -> str:
        return "report"


class StoragePluginCollector(PluginCollectorBase):
    def plugin_type(self) -> str:
        return "storage"

    def aux_info(self, metadata_collector) -> Dict[str, Any]:
        info = metadata_collector.extract_info(
            "import json; "
            "queries = plugin.storage_provider.example_queries(); "
            "print(json.dumps({'example_queries': ["
            "{'query': qry.query, 'desc': qry.description, 'type': qry.type.name.lower()} "
            "for qry in queries]}))"
        )
        return json.loads(info)


class LoggerPluginCollector(PluginCollectorBase):
    def plugin_type(self):
        return "logger"


def collect_plugins():
    templates = Environment(
        loader=FileSystemLoader("_templates"),
        autoescape=select_autoescape(),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    plugins = defaultdict(list)

    with PyPISimple() as pypi_client:
        packages = pypi_client.get_index_page().projects

    for collector in (
        ExecutorPluginCollector,
        StoragePluginCollector,
        ReportPluginCollector,
        LoggerPluginCollector,
    ):
        collector().collect_plugins(plugins, packages, templates)

    with open("index.rst", "w") as f:
        f.write(templates.get_template("index.rst.j2").render(plugins=plugins))


def get_docs(repository: str, section: str, branches=["main", "master"]):
    if repository is None:
        return None

    def retrieve():
        for branch in branches:
            if repository.startswith("https://github.com"):
                docs = requests.get(
                    f"{repository}/blob/{branch}/docs/{section}.md?raw=true"
                )
                if docs.status_code == 200:
                    return docs.text
            elif repository.startswith("https://gitlab.com"):
                docs = requests.get(
                    f"{repository}/-/raw/{branch}/docs/{section}.md?raw=true"
                )
                if docs.status_code == 200:
                    return docs.text

    retrieved = retrieve()
    if retrieved is not None:
        return m2r2.convert(retrieved)
    else:
        return None
