
"""Loader for the shared site configuration (config/site.json).

Both the anchor source and the (future) location engine load the site through
this module so there is exactly one place that knows the file layout.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

SCHEMA = "uwb.site/1"

# .../Model/shared/site_config.py -> .../Model/config/site.json
_DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "site.json"
)


def load_site(path: str | None = None) -> Dict[str, Any]:
    path = path or os.environ.get("SITE_CONFIG", _DEFAULT_PATH)
    with open(path, "r", encoding="utf-8") as fh:
        site = json.load(fh)
    if site.get("schema") != SCHEMA:
        raise ValueError(f"Unsupported site schema {site.get('schema')!r} (expected {SCHEMA!r})")
    return site


def anchors_by_id(site: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {a["id"]: a for a in site["anchors"]}
