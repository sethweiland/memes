"""302 redirects from pre-IA meme URLs so bookmarks keep working."""

from __future__ import annotations

from flask import Flask, redirect, request

# Old top-level meme prefixes → /memes/<same>
_PREFIX_MOVES = (
    ("/generate", "/memes/generate"),
    ("/gallery", "/memes/gallery"),
    ("/templates", "/memes/templates"),
    ("/video", "/memes/video"),
    ("/discovery", "/memes/discovery"),
)


def _with_query(path: str) -> str:
    qs = request.query_string.decode()
    if qs:
        return f"{path}?{qs}"
    return path


def register_legacy_redirects(app: Flask) -> None:
    for old, new in _PREFIX_MOVES:
        def _make(new_base: str):
            def _redir(path: str | None = None):
                dest = new_base.rstrip("/") + "/"
                if path:
                    dest = f"{new_base.rstrip('/')}/{path}"
                return redirect(_with_query(dest), code=302)

            return _redir

        view = _make(new)
        slug = old.strip("/").replace("/", "_")
        app.add_url_rule(old, endpoint=f"legacy_{slug}", view_func=view)
        app.add_url_rule(f"{old}/", endpoint=f"legacy_{slug}_root", view_func=view)
        app.add_url_rule(f"{old}/<path:path>", endpoint=f"legacy_{slug}_path", view_func=view)

    def _daily_queue():
        return redirect(_with_query("/memes/gallery/daily-candidates/"), code=302)

    app.add_url_rule("/memes/daily-queue", endpoint="legacy_daily_queue", view_func=_daily_queue)
    app.add_url_rule("/memes/daily-queue/", endpoint="legacy_daily_queue_root", view_func=_daily_queue)
