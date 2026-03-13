from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import git
import git.exc
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
from typing import Any, Dict, List, Optional
import uuid
from packaging.specifiers import SpecifierSet
from packaging.version import Version
from pypi_simple import PyPISimple

import requests
from ratelimit import limits, sleep_and_retry
from jinja2 import Environment, FileSystemLoader, select_autoescape
import m2r2


TEST_PACKAGES = (
    [
        package.strip()
        for package in os.environ.get("TEST_PACKAGES").split(",")
        if package.strip()
    ]
    if "TEST_PACKAGES" in os.environ
    else None
)


@sleep_and_retry
@limits(calls=20, period=1)
def pypi_api(query, accept="application/json"):
    res = requests.get(
        query,
        headers={
            "Accept": accept,
            "User-Agent": "Snakemake plugin catalog (https://github.com/snakemake/snakemake-plugin-catalog)",
        },
    )
    if res.status_code != 200:
        raise MetadataError(f"API request {query} failed with status {res.status_code}")
    return res.json()


class MetadataError(Exception):
    def log(self, package: str) -> None:
        print(
            f"Error installing {package} or retrieving metadata: {self}",
            file=sys.stderr,
        )


class MetadataCollector:
    """
    Collect metadata on a plugin `package` of a specific `plugin_type` by installing it
    in a temporary working directory specific to each class instance.
    """

    def __init__(self, package: str, plugin_type: str, version: str):
        self.envname = uuid.uuid4().hex
        self.package = package
        self.version = version
        self.plugin_type = plugin_type
        self.tempdir = None

    @property
    def plugin_name(self):
        return self.package.removeprefix(f"snakemake-{self.plugin_type}-plugin-")

    @property
    def registry(self):
        return f"{self.plugin_type.title()}PluginRegistry"

    def _run(
        self, cmd: List[str], stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    ) -> subprocess.CompletedProcess:
        assert self.tempdir is not None
        return subprocess.run(
            cmd,
            cwd=self.tempdir.name,
            stdout=stdout,
            stderr=stderr,
            check=True,
        )

    def __enter__(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self._run(["pixi", "init", "--channel", "conda-forge", "--channel", "bioconda"])
        self._run(
            [
                "pixi",
                "task",
                "add",
                "--arg",
                "statement",
                "extract-info",
                f"python -c \"from snakemake_interface_{self.plugin_type}_plugins.registry import {self.registry}; plugin = {self.registry}().get_plugin('{self.plugin_name}'); {{{{statement}}}}\"",
            ]
        )

        def pixi_add(args=None):
            """
            Add the package for which metadata is to be parsed to the temporary
            workspace.
            """
            args = args or []
            self._run(["pixi", "add", f"{self.package}=={self.version}"] + args)

        # try conda first
        try:
            pixi_add(["snakemake-minimal"])
            return self
        except subprocess.CalledProcessError:
            pass

        # and now plain python
        py_ver = sys.version_info
        error = None

        for py_minor in range(py_ver.minor, 7, -1):
            py_ver_constraint = f"{py_ver.major}.{py_minor}"

            try:
                self._run(["pixi", "add", f"python={py_ver_constraint}"])
                pixi_add(["snakemake", "--pypi"])
                return self
            except subprocess.CalledProcessError as e:
                if error is None:
                    error = e.stdout.decode()

        assert error is not None
        raise MetadataError(f"Cannot be installed: {error}")

    def __exit__(self, exc_type, exc_value, traceback):
        assert self.tempdir is not None
        self.tempdir.cleanup()

    def extract_info(self, statement: str) -> str:
        try:
            res = self._run(
                ["pixi", "run", "extract-info", statement], stderr=subprocess.PIPE
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

    def collect_plugins(self, plugins, packages, templates, snakemake_compat_index):
        """
        Collect plugins of the type of the corresponding plugin type collector class.
        Plugins are selected from the set of ALL pypi packages by matching names to the
        expected prefix of 'snakemake-{plugin_type}-plugin-'. For each matching package
        metadata is then extracted, the provided `templates` are rendered using this
        information, and the plugin name is appended to `plugins`.
        """
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
            try:
                meta = pypi_api(f"https://pypi.org/pypi/{package}/json")
            except MetadataError as e:
                e.log(package)
                print(
                    f"Skipping {package} because pypi does not provide metadata.",
                    file=sys.stderr,
                )
                continue
            plugin_name = package.removeprefix(prefix)
            desc = "\n".join(meta["info"]["description"].split("\n")[2:])
            version = meta["info"]["version"]

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
            info = meta.get("info") or dict()
            project_urls = info.get("project_urls") or dict()

            author_info = info.get("author") or info.get("author_email")
            authors = (
                [author.strip() for author in author_info.split(",")]
                if author_info
                else []
            )

            repository = project_urls.get("Repository") or project_urls.get(
                "repository"
            )
            # Clean up repository URL early - remove .git suffix and trailing slashes
            if repository:
                repository = repository.replace(".git", "").rstrip("/")

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

            commit_info = None
            commit_url = repository
            docs_intro = None
            docs_further = None

            # Fetch git info (commit + docs) in a single clone operation
            if repository and (git_info := _get_plugin_git_info(repository)):
                if git_info.commit:
                    commit_info = {
                        "sha": git_info.commit.sha,
                        "date": git_info.commit.date,
                    }
                    commit_url = _commit_url(
                        repository, repository_type, git_info.commit.sha
                    )

                # Convert docs from markdown to RST
                docs_intro = _convert_markdown_to_rst(git_info.docs.intro, "intro")
                docs_further = _convert_markdown_to_rst(
                    git_info.docs.further, "further"
                )

                if docs_intro is None and docs_further is None:
                    docs_warning = (
                        f"No documentation found in repository {repository}. The plugin should "
                        "provide a docs/intro.md with some introductory sentences and "
                        "optionally a docs/further.md file with details beyond the "
                        "auto-generated usage instructions presented in this catalog."
                    )

            commit_date_label = (
                _commit_date_label(commit_info["date"]) if commit_info else None
            )
            commit_age_color = (
                _commit_age_color(commit_info["date"]) if commit_info else None
            )

            snakemake_version = _plugin_min_snakemake(
                meta["info"].get("requires_dist"), snakemake_compat_index
            )

            settings = {}
            aux_info = {}

            try:
                with MetadataCollector(package, plugin_type, version) as collector:
                    settings = collector.get_settings()
                    aux_info = self.aux_info(collector)
            except MetadataError as e:
                error = str(e)
                e.log(package)
                # go on, just with error registered for display

            if error is not None:
                if repository is not None:
                    error += f"\n\nPlease file a corresponding issue in the plugin's `repository <{repository}>`__ (if there is none yet)."
                else:
                    error += "\n\nPlease contact the plugin authors."

            # Get repository shortname for shields.io badges
            repo_shortname = get_repo_shortname(repository) if repository else None

            rendered = templates.get_template(f"{plugin_type}_plugin.rst.j2").render(
                plugin_name=plugin_name,
                package_name=package,
                authors=authors,
                repository=repository,
                repo_shortname=repo_shortname,
                repository_type=repository_type,
                commit_info=commit_info,
                commit_url=commit_url,
                commit_age_color=commit_age_color,
                commit_date_label=commit_date_label,
                snakemake_version=snakemake_version,
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


class SchedulerPluginCollector(PluginCollectorBase):
    def plugin_type(self):
        return "scheduler"


def _commit_date_label(date_str: str) -> str:
    """Return a shields.io-safe date label like 'March_2026' from an ISO date string."""
    return datetime.fromisoformat(date_str.replace("Z", "+00:00")).strftime("%B_%Y")


def _commit_url(
    repository: str, repository_type: Optional[str], commit_sha: str
) -> str:
    """Construct commit URL based on repository type.

    Args:
        repository: Base repository URL
        repository_type: Type of repository ('github', 'gitlab', or None)
        commit_sha: Commit SHA hash

    Returns:
        Full URL to the specific commit
    """
    if repository_type == "github":
        return f"{repository}/commit/{commit_sha}"
    elif repository_type == "gitlab":
        return f"{repository}/-/commit/{commit_sha}"
    else:
        return repository


def get_repo_shortname(repository: Optional[str]) -> str:
    """Extract the shortname from repository URL for shields.io badges.

    Removes protocol and known forge prefix (https://github.com/ or https://gitlab.com/),
    returning just the user/repo path.

    Args:
        repository: Full repository URL (e.g., https://github.com/user/repo)

    Returns:
        Repository shortname (e.g., user/repo)
    """
    if not repository:
        return ""

    # Remove protocol and domain prefixes
    cleaned = (
        repository.replace("https://github.com/", "")
        .replace("https://gitlab.com/", "")
        .replace("http://github.com/", "")
        .replace("http://gitlab.com/", "")
    )

    return cleaned


def _commit_age_color(date_str: str) -> str:
    """Return a shields.io color hex based on how old the commit date is."""
    dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    months = (now.year - dt.year) * 12 + (now.month - dt.month)
    if months < 6:
        return "%2316a34a"  # green
    elif months < 24:
        return "%23ea580c"  # orange
    else:
        return "%23dc2626"  # red


_INTERFACE_PKG_RE = re.compile(
    r"(snakemake-interface-(?:executor|storage|report|logger|scheduler)-plugins)"
    r"\s*\(?([^)]+)"
)


def _build_snakemake_compat_index() -> list[tuple]:
    """Build compatibility index mapping Snakemake versions to interface requirements.

    Returns a sorted list of (snakemake_version, interface_pkg, lower, upper) tuples
    where lower/upper are Version objects (or None) representing the interface version range
    that each Snakemake version requires.

    Example: (Version("8.0.0"), "snakemake-interface-executor-plugins", Version("1.0"), Version("2.0"))
    means Snakemake 8.0 requires executor interface >=1.0,<2.0
    """
    print("Building Snakemake compatibility index...", file=sys.stderr)
    meta = pypi_api("https://pypi.org/pypi/snakemake/json")

    # Get all non-prerelease versions >= 8.0.0
    all_versions = sorted(
        [
            v
            for v in meta["releases"]
            if not Version(v).is_prerelease and Version(v) >= Version("8.0.0")
        ],
        key=Version,
    )

    # Build index by checking versions and deduplicating when requirements don't change
    # This handles cases where interface requirements change mid-minor version
    # (e.g., 8.10.3 has different requirements than 8.10.0)
    entries = []
    prev_requirements = {}  # iface_pkg -> (lower, upper)

    for snakemake_ver in all_versions:
        try:
            ver_meta = pypi_api(f"https://pypi.org/pypi/snakemake/{snakemake_ver}/json")
        except MetadataError:
            continue

        current_requirements = {}
        for dep in ver_meta["info"].get("requires_dist") or []:
            match = _INTERFACE_PKG_RE.search(dep)
            if not match:
                continue

            iface_pkg = match.group(1)
            spec = SpecifierSet(match.group(2).strip())

            # Extract lower and upper bounds from specifier set
            lower = upper = None
            for s in spec:
                v = Version(s.version)
                if s.operator in (">=", ">"):
                    lower = v if lower is None else max(lower, v)
                elif s.operator in ("<", "<="):
                    upper = v if upper is None else min(upper, v)

            current_requirements[iface_pkg] = (lower, upper)

        # Only add entry if requirements changed from previous version
        if current_requirements != prev_requirements:
            for iface_pkg, (lower, upper) in current_requirements.items():
                entries.append((Version(snakemake_ver), iface_pkg, lower, upper))
            prev_requirements = current_requirements

    return sorted(entries, key=lambda e: e[0])


def _plugin_min_snakemake(
    requires_dist: list[str] | None,
    compat_index: list[tuple],
) -> str | None:
    """Return the minimum Snakemake version compatible with a plugin.

    A plugin is compatible with a Snakemake version if their interface version requirements overlap.

    Example:
        Plugin requires: interface >=2.5
        Snakemake 8.1 requires: interface >=2.0,<3.0
        Overlap: [2.5, 3.0) -> Compatible!

        Plugin requires: interface >=1.5
        Snakemake 8.1 requires: interface >=2.0,<3.0
        No overlap: plugin allows 1.5-1.9 which Snakemake doesn't support -> Incompatible

    Returns:
        Minimum Snakemake version string like ">=8.1" or None if incompatible
    """
    if not requires_dist:
        return None

    # Extract plugin's interface requirement
    plugin_iface = None
    plugin_lower = None
    for dep in requires_dist:
        match = _INTERFACE_PKG_RE.search(dep)
        if match:
            plugin_iface = match.group(1)
            spec = SpecifierSet(match.group(2).strip())
            for s in spec:
                if s.operator in (">=", ">"):
                    v = Version(s.version)
                    plugin_lower = v if plugin_lower is None else max(plugin_lower, v)
            break

    if plugin_lower is None or plugin_iface is None:
        return None

    # Find first Snakemake version with overlapping interface requirement
    for snakemake_ver, iface_pkg, snakemake_lower, snakemake_upper in compat_index:
        if iface_pkg != plugin_iface:
            continue

        # Check if [plugin_lower, ∞) overlaps with [snakemake_lower, snakemake_upper)
        # No overlap if plugin needs older version than Snakemake provides
        if snakemake_lower is not None and plugin_lower < snakemake_lower:
            continue

        # No overlap if plugin needs newer version than Snakemake supports
        if snakemake_upper is not None and plugin_lower >= snakemake_upper:
            continue

        # Found compatible version
        return f">={snakemake_ver.major}.{snakemake_ver.minor}"

    return None


def collect_plugins():
    templates = Environment(
        loader=FileSystemLoader("_templates"),
        autoescape=select_autoescape(),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    plugins = defaultdict(list)
    snakemake_compat_index = _build_snakemake_compat_index()

    with PyPISimple() as pypi_client:
        packages = pypi_client.get_index_page().projects

    for collector in (
        ExecutorPluginCollector,
        StoragePluginCollector,
        ReportPluginCollector,
        LoggerPluginCollector,
        SchedulerPluginCollector,
    ):
        collector().collect_plugins(
            plugins, packages, templates, snakemake_compat_index
        )

    with open("index.rst", "w") as f:
        f.write(templates.get_template("index.rst.j2").render(plugins=plugins))


SECTION_MARK_ORDER = '#*=-^"~:`_+<'


@dataclass
class CommitInfo:
    """Metadata about the latest commit."""

    sha: str
    date: str


@dataclass
class PluginDocs:
    """Documentation files from the plugin repository."""

    intro: Optional[str]
    further: Optional[str]


@dataclass
class PluginGitInfo:
    """Git information for a plugin."""

    commit: Optional[CommitInfo]
    docs: PluginDocs


def _get_plugin_git_info(
    repo_url: str, branches: Optional[List[str]] = None
) -> PluginGitInfo:
    """Clone the plugin repo once (bare) and return docs + commit info."""

    if branches is None:
        branches = ["main", "master"]

    for branch in branches:
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = git.Repo.clone_from(repo_url, to_path=tmpdir, bare=True)

                # commit metadata
                commit = repo.commit(branch)
                commit_info = CommitInfo(
                    sha=commit.hexsha[:7],
                    date=commit.committed_datetime.isoformat(),
                )

                # docs
                def _show(section: str) -> Optional[str]:
                    try:
                        return repo.git.show(f"{branch}:docs/{section}.md")
                    except git.GitCommandError:
                        return None

                docs = PluginDocs(intro=_show("intro"), further=_show("further"))
                return PluginGitInfo(commit=commit_info, docs=docs)
        except git.exc.BadName:
            print(
                f"Warning: Branch '{branch}' not found in {repo_url}, trying next branch...",
                file=sys.stderr,
            )
            continue
        except git.GitCommandError as e:
            # Clone failures or other git errors
            print(
                f"Git error accessing {repo_url} on branch '{branch}': {e}",
                file=sys.stderr,
            )
            continue

    return PluginGitInfo(commit=None, docs=PluginDocs(intro=None, further=None))


def _convert_markdown_to_rst(
    markdown_content: Optional[str], section: str
) -> Optional[str]:
    """
    Convert markdown documentation to RST format.

    Args:
        markdown_content: Markdown content to convert
        section: Documentation section ('intro' or 'further') to determine heading marks

    Returns:
        Converted RST documentation or None if input is None
    """
    if markdown_content is None:
        return None

    renderer = m2r2.RestRenderer()
    renderer.hmarks = {
        i + 1: mark
        for i, mark in enumerate(
            SECTION_MARK_ORDER[3:] if section == "further" else SECTION_MARK_ORDER[2:]
        )
    }
    return m2r2.convert(markdown_content, renderer=renderer)
