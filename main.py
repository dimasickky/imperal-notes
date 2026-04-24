"""Notes v3.0.0 · Personal notes with folders, trash, full-text search.

SDK v2.0.0 / Webbee Single Voice — class-based tool surface, no ChatExtension,
no per-extension system prompt. Webbee Narrator renders all user-facing prose
from the typed output schemas in ``schemas.py``.

Bootstrap order:
1. Prepend own dir to sys.path so sibling modules resolve as top-level names
   (``import app`` etc.) under the kernel's isolated loader.
2. Purge any cached modules from a previous load of this extension — the
   kernel loader does a best-effort purge too, but belt-and-braces here
   keeps hot-reload in dev predictable.
3. Import ``app`` — instantiates the Extension instance (``ext``), which the
   kernel loader discovers by duck-typing (``hasattr(attr, 'tools')``).
4. Import side-effect modules that register panels / skeleton / editor UI
   against the ``ext`` instance from ``app``.
"""
from __future__ import annotations

import os
import sys

_dir = os.path.dirname(os.path.abspath(__file__))
if _dir not in sys.path:
    sys.path.insert(0, _dir)

for _m in [
    k for k in list(sys.modules)
    if k in (
        "app", "tools", "schemas",
        "skeleton", "panels", "panels_editor",
    )
]:
    del sys.modules[_m]

from app import ext  # noqa: F401,E402  (loader discovers this)

import skeleton       # noqa: F401,E402
import panels         # noqa: F401,E402
import panels_editor  # noqa: F401,E402
