"""URL prefix helpers for reverse-proxy and subpath GDS deployments."""

from __future__ import annotations


def normalize_application_root(value: str | None) -> str:
    """Normalize CLI/env root path to '' or '/segment' without trailing slash."""
    if not value:
        return ""
    root = value.strip()
    if not root.startswith("/"):
        root = f"/{root}"
    return root.rstrip("/")


class ScriptNameMiddleware:
    """Strip a configured SCRIPT_NAME prefix from incoming WSGI requests."""

    def __init__(self, app, script_name: str):
        self.app = app
        self.script_name = normalize_application_root(script_name)

    def __call__(self, environ, start_response):
        if self.script_name:
            environ["SCRIPT_NAME"] = self.script_name
            path_info = environ.get("PATH_INFO", "")
            if path_info.startswith(self.script_name):
                stripped = path_info[len(self.script_name) :]
                environ["PATH_INFO"] = stripped if stripped else "/"
        return self.app(environ, start_response)
