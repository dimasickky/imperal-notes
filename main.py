"""Notes v2.4.0 · Personal notes with AI assistant + DUI panels."""
from __future__ import annotations

import sys, os
_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _dir)
for _m in [k for k in sys.modules if k in ("app", "handlers_notes", "handlers_folders",
                                            "handlers_panel_actions", "skeleton",
                                            "panels", "panels_editor")]:
    del sys.modules[_m]

from app import ext, chat  # noqa: F401

import handlers_notes          # noqa: F401
import handlers_folders        # noqa: F401
import handlers_panel_actions  # noqa: F401
import skeleton                # noqa: F401
import panels                  # noqa: F401
import panels_editor           # noqa: F401
