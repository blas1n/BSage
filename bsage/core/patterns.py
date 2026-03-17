"""Shared regex patterns used across BSage modules."""

from __future__ import annotations

import re

# Wiki-link extraction: [[target]] or [[target|display text]]
WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
