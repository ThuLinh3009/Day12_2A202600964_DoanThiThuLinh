"""
Entry point for Day 09 Shopping Assistant.
Loads src/app/graph.py without colliding with Day12's app package.
"""
import sys
import os

_src_dir = os.path.dirname(os.path.abspath(__file__))


def load_assistant():
    src = _src_dir

    # 1. Save ALL app.* entries (Day12 modules)
    saved_modules = {k: sys.modules[k]
                     for k in list(sys.modules)
                     if k == "app" or k.startswith("app.")}

    # 2. Remove them so Python re-searches sys.path
    for k in saved_modules:
        del sys.modules[k]

    # 3. Force src to position 0 unconditionally
    saved_path = sys.path.copy()
    sys.path = [src] + [p for p in sys.path if p != src]

    try:
        from app.config import Settings
        from app.graph import ShoppingAssistant
        return ShoppingAssistant, Settings
    finally:
        # 4. Restore sys.path
        sys.path = saved_path
        # 5. Fully restore ALL Day12 app.* modules (overwrite anything loaded by Day09)
        sys.modules.update(saved_modules)
