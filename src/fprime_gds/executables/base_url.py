"""Utilities and command-line parsing for serving the GDS below a URL prefix."""

from typing import Any, Dict, Tuple
from urllib.parse import unquote, urlsplit

from fprime_gds.executables.cli import ParserBase


def normalize_base_url(value: str) -> str:
    """Normalize a GDS base URL path.

    The GDS accepts a path prefix only, not an absolute URL. The root path is
    represented internally as an empty string so that prefixing ``/channels``
    preserves the existing route.
    """
    value = (value or "").strip()
    if value in ("", "/"):
        return ""

    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("base URL must be a path without scheme, host, query, or fragment")

    path = f"/{parsed.path.strip('/')}"
    decoded_segments = [unquote(segment) for segment in path.split("/")[1:]]
    if any(
        not segment
        or segment in (".", "..")
        or "/" in segment
        or "\\" in segment
        for segment in decoded_segments
    ):
        raise ValueError("base URL contains an invalid path segment")
    return path


def with_base_url(base_url: str, path: str) -> str:
    """Prefix an application route with ``base_url``."""
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{normalize_base_url(base_url)}{path}"


class BaseUrlParser(ParserBase):
    """Parse the URL prefix used to serve the HTML GDS."""

    DESCRIPTION = "Web UI path options"

    def get_arguments(self) -> Dict[Tuple[str, ...], Dict[str, Any]]:
        return {
            ("--base-url",): {
                "dest": "base_url",
                "action": "store",
                "default": "",
                "required": False,
                "type": normalize_base_url,
                "help": "Serve the HTML GDS below this URL path (for example: /mission/gds).",
            }
        }

    def handle_arguments(self, args, **kwargs):
        return args
