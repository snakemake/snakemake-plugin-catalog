"""Unit tests for collect_plugins."""

from packaging.version import Version

from collect_plugins import (
    _convert_markdown_to_rst,
    _plugin_min_snakemake,
    _commit_url,
    get_repo_shortname,
)


# Markdown conversion tests


def test_convert_markdown_to_rst_none():
    """Test markdown conversion handles None input."""
    assert _convert_markdown_to_rst(None, "intro") is None


def test_convert_markdown_to_rst_intro_heading_levels():
    """Test intro section uses correct RST heading marks."""
    result = _convert_markdown_to_rst("# H1\n## H2\n### H3", "intro")
    assert result is not None
    # intro starts at SECTION_MARK_ORDER[2:], so # -> =, ## -> -, ### -> ^
    assert "=" in result  # H1 underline
    assert "-" in result  # H2 underline


def test_convert_markdown_to_rst_further_heading_levels():
    """Test further section uses correct RST heading marks."""
    result = _convert_markdown_to_rst("# H1\n## H2", "further")
    assert result is not None
    # further starts at SECTION_MARK_ORDER[3:], so # -> -, ## -> ^
    assert "-" in result  # H1 underline


def test_convert_markdown_to_rst_preserves_content():
    """Test markdown content is preserved during conversion."""
    markdown = "# Title\n\nSome **bold** text.\n\n- Item 1\n- Item 2"
    result = _convert_markdown_to_rst(markdown, "intro")
    assert result is not None
    assert "Title" in result
    assert "bold" in result
    assert "Item 1" in result


# Compatibility index tests


def test_plugin_min_snakemake_exact_match():
    """Plugin requirement exactly matches Snakemake's lower bound."""
    compat_index = [
        (
            Version("8.0.0"),
            "snakemake-interface-executor-plugins",
            Version("1.0"),
            Version("2.0"),
        ),
    ]
    requires = ["snakemake-interface-executor-plugins (>=1.0)"]
    result = _plugin_min_snakemake(requires, compat_index)
    assert result == ">=8.0"


def test_plugin_min_snakemake_plugin_too_old():
    """Plugin requires older version than Snakemake provides."""
    compat_index = [
        (
            Version("8.0.0"),
            "snakemake-interface-executor-plugins",
            Version("2.0"),
            Version("3.0"),
        ),
    ]
    requires = ["snakemake-interface-executor-plugins (>=1.5)"]
    result = _plugin_min_snakemake(requires, compat_index)
    # Plugin requires >=1.5 but Snakemake needs >=2.0, so incompatible
    assert result is None


def test_plugin_min_snakemake_plugin_too_new():
    """Plugin requires newer version than Snakemake provides."""
    compat_index = [
        (
            Version("8.0.0"),
            "snakemake-interface-executor-plugins",
            Version("1.0"),
            Version("2.0"),
        ),
    ]
    requires = ["snakemake-interface-executor-plugins (>=2.5)"]
    result = _plugin_min_snakemake(requires, compat_index)
    # Plugin requires >=2.5 but Snakemake supports <2.0, so incompatible
    assert result is None


def test_plugin_min_snakemake_within_range():
    """Plugin requirement falls within Snakemake's range."""
    compat_index = [
        (
            Version("8.0.0"),
            "snakemake-interface-executor-plugins",
            Version("1.0"),
            Version("3.0"),
        ),
    ]
    requires = ["snakemake-interface-executor-plugins (>=1.5)"]
    result = _plugin_min_snakemake(requires, compat_index)
    assert result == ">=8.0"


def test_plugin_min_snakemake_multiple_versions():
    """Find first compatible Snakemake version among multiple."""
    compat_index = [
        (
            Version("8.0.0"),
            "snakemake-interface-executor-plugins",
            Version("1.0"),
            Version("2.0"),
        ),
        (
            Version("8.1.0"),
            "snakemake-interface-executor-plugins",
            Version("2.0"),
            Version("3.0"),
        ),
        (
            Version("8.2.0"),
            "snakemake-interface-executor-plugins",
            Version("3.0"),
            Version("4.0"),
        ),
    ]
    requires = ["snakemake-interface-executor-plugins (>=2.5)"]
    result = _plugin_min_snakemake(requires, compat_index)
    # Plugin >=2.5 is compatible with 8.1.0 [2.0, 3.0)
    assert result == ">=8.1"


def test_plugin_min_snakemake_no_upper_bound():
    """Snakemake has no upper bound."""
    compat_index = [
        (
            Version("8.0.0"),
            "snakemake-interface-executor-plugins",
            Version("1.0"),
            None,
        ),
    ]
    requires = ["snakemake-interface-executor-plugins (>=1.5)"]
    result = _plugin_min_snakemake(requires, compat_index)
    assert result == ">=8.0"


def test_plugin_min_snakemake_no_lower_bound():
    """Snakemake has no lower bound."""
    compat_index = [
        (
            Version("8.0.0"),
            "snakemake-interface-executor-plugins",
            None,
            Version("2.0"),
        ),
    ]
    requires = ["snakemake-interface-executor-plugins (>=1.5)"]
    result = _plugin_min_snakemake(requires, compat_index)
    assert result == ">=8.0"


def test_plugin_min_snakemake_empty_requires():
    """Plugin has no requirements."""
    compat_index = [
        (
            Version("8.0.0"),
            "snakemake-interface-executor-plugins",
            Version("1.0"),
            Version("2.0"),
        ),
    ]
    result = _plugin_min_snakemake(None, compat_index)
    assert result is None


def test_plugin_min_snakemake_no_interface_requirement():
    """Plugin has requirements but no interface plugin requirement."""
    compat_index = [
        (
            Version("8.0.0"),
            "snakemake-interface-executor-plugins",
            Version("1.0"),
            Version("2.0"),
        ),
    ]
    requires = ["requests (>=2.0)"]
    result = _plugin_min_snakemake(requires, compat_index)
    assert result is None


def test_plugin_min_snakemake_different_interface():
    """Plugin requires different interface type."""
    compat_index = [
        (
            Version("8.0.0"),
            "snakemake-interface-executor-plugins",
            Version("1.0"),
            Version("2.0"),
        ),
    ]
    requires = ["snakemake-interface-storage-plugins (>=1.0)"]
    result = _plugin_min_snakemake(requires, compat_index)
    # No matching interface in index
    assert result is None


def test_plugin_min_snakemake_edge_case_at_upper_bound():
    """Plugin lower bound equals Snakemake upper bound (exclusive)."""
    compat_index = [
        (
            Version("8.0.0"),
            "snakemake-interface-executor-plugins",
            Version("1.0"),
            Version("2.0"),
        ),
    ]
    requires = ["snakemake-interface-executor-plugins (>=2.0)"]
    result = _plugin_min_snakemake(requires, compat_index)
    # Plugin >=2.0 doesn't overlap with [1.0, 2.0)
    assert result is None


# Commit URL construction tests


def test_commit_url_github():
    """Test GitHub commit URL construction."""
    url = _commit_url("https://github.com/user/repo", "github", "abc1234")
    assert url == "https://github.com/user/repo/commit/abc1234"


def test_commit_url_gitlab():
    """Test GitLab commit URL construction."""
    url = _commit_url("https://gitlab.com/user/repo", "gitlab", "abc1234")
    assert url == "https://gitlab.com/user/repo/-/commit/abc1234"


def test_commit_url_unknown_type():
    """Test unknown repository type returns base URL."""
    url = _commit_url("https://example.com/repo", None, "abc1234")
    assert url == "https://example.com/repo"


def test_commit_url_unknown_type_non_none():
    """Test unknown repository type string returns base URL."""
    url = _commit_url("https://bitbucket.org/user/repo", "bitbucket", "abc1234")
    assert url == "https://bitbucket.org/user/repo"


# Repository shortname extraction tests


def test_get_repo_shortname_github_https():
    """Test extracting shortname from GitHub HTTPS URL."""
    shortname = get_repo_shortname("https://github.com/user/repo")
    assert shortname == "user/repo"


def test_get_repo_shortname_gitlab_https():
    """Test extracting shortname from GitLab HTTPS URL."""
    shortname = get_repo_shortname("https://gitlab.com/user/repo")
    assert shortname == "user/repo"


def test_get_repo_shortname_http_protocol():
    """Test extracting shortname from HTTP protocol URL."""
    shortname = get_repo_shortname("http://github.com/user/repo")
    assert shortname == "user/repo"


def test_get_repo_shortname_empty_string():
    """Test extracting shortname from empty string."""
    shortname = get_repo_shortname("")
    assert shortname == ""


def test_get_repo_shortname_none():
    """Test extracting shortname from None value."""
    shortname = get_repo_shortname(None)
    assert shortname == ""


def test_get_repo_shortname_other_domain():
    """Test URL from other domain remains unchanged."""
    shortname = get_repo_shortname("https://bitbucket.org/user/repo")
    assert shortname == "https://bitbucket.org/user/repo"
