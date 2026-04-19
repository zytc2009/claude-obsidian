"""Capture importers for platform-specific content extraction."""

from .base import ImportResult, BaseImporter
from .router import detect_platform, fetch_url

