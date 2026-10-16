# tests/test_urlutils.py
# ----------------------
# What it does: Unit tests for URL normalization and domain extraction.
# Talks to: pagewatch/urlutils.py, pagewatch/config.py

import pytest
from pagewatch.urlutils import normalize_url, get_domain
from pagewatch import config


class TestNormalizeUrl:
    """Tests for normalize_url function."""

    def test_strip_trailing_slash_root(self):
        """Root trailing slash should be stripped."""
        assert normalize_url("https://example.com/") == "https://example.com"

    def test_strip_trailing_slash_path(self):
        """Trailing slash on path should be stripped."""
        assert normalize_url("https://example.com/products/") == "https://example.com/products"

    def test_lowercase_scheme_and_host(self):
        """Scheme and hostname should be lowercased, but path casing preserved."""
        assert normalize_url("HTTP://Example.COM/Path/To/Item") == "http://example.com/Path/To/Item"

    def test_strip_fragment(self):
        """Fragment like #section should be stripped."""
        assert normalize_url("https://example.com/page#reviews") == "https://example.com/page"

    def test_preserve_query_string(self):
        """Query parameters should be preserved."""
        assert normalize_url("https://example.com/search?q=phone&sort=asc") == "https://example.com/search?q=phone&sort=asc"

    def test_preserve_port(self):
        """Port numbers should be preserved and host lowercased."""
        assert normalize_url("http://LOCALHOST:5001/api/") == "http://localhost:5001/api"

    def test_reject_empty_and_whitespace(self):
        """Empty or whitespace URL should raise ValueError."""
        with pytest.raises(ValueError, match="URL cannot be empty"):
            normalize_url("")
        with pytest.raises(ValueError, match="URL cannot be empty"):
            normalize_url("   ")

    def test_reject_invalid_scheme(self):
        """Schemes other than http/https should raise ValueError."""
        with pytest.raises(ValueError, match="URL must start with http:// or https://"):
            normalize_url("ftp://example.com/file.txt")
        with pytest.raises(ValueError, match="URL must start with http:// or https://"):
            normalize_url("javascript:alert(1)")
        with pytest.raises(ValueError, match="URL must start with http:// or https://"):
            normalize_url("file:///C:/test.txt")

    def test_reject_no_scheme(self):
        """URLs without http/https should raise ValueError."""
        with pytest.raises(ValueError, match="URL must start with http:// or https://"):
            normalize_url("example.com/page")

    def test_localhost_allowed_by_default(self, monkeypatch):
        """Localhost should be accepted when ALLOW_LOCALHOST is True."""
        monkeypatch.setattr(config, "ALLOW_LOCALHOST", True)
        assert normalize_url("http://127.0.0.1:5000/") == "http://127.0.0.1:5000"
        assert normalize_url("http://localhost:5001/") == "http://localhost:5001"

    def test_localhost_rejected_when_disabled(self, monkeypatch):
        """Localhost should raise ValueError when ALLOW_LOCALHOST is False."""
        monkeypatch.setattr(config, "ALLOW_LOCALHOST", False)
        with pytest.raises(ValueError, match="Monitoring localhost or internal addresses is not allowed"):
            normalize_url("http://127.0.0.1:5000/")
        with pytest.raises(ValueError, match="Monitoring localhost or internal addresses is not allowed"):
            normalize_url("http://localhost:5001/")


class TestGetDomain:
    """Tests for get_domain function."""

    def test_standard_domain(self):
        """Extracts standard domain name."""
        assert get_domain("https://www.example.com/path") == "www.example.com"

    def test_domain_with_port(self):
        """Extracts hostname without port."""
        assert get_domain("http://127.0.0.1:5001/items") == "127.0.0.1"

    def test_uppercased_domain(self):
        """Returns lowercased domain name."""
        assert get_domain("HTTP://BLOG.Example.ORG/") == "blog.example.org"

    def test_invalid_url(self):
        """Returns empty string for bad input."""
        assert get_domain("not-a-valid-url") == ""
