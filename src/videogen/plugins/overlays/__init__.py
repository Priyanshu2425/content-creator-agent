"""Overlay plugins: zoom, pan, insert, title (Phase 6, texthook/01).

Each overlay type occupies its own folder holding contract.py (classification + param validation +
registry entry) and ir.py (the pure to_ir facet). Importing this package registers every built-in
overlay into the default registry (the import side effect the kernel registry triggers lazily on
first use), so the registry stays the single source of truth -- exactly as the Layout plugins do.
"""

from videogen.plugins.overlays import (  # noqa: F401 -- import registers built-ins
    insert,
    pan,
    title,
    zoom,
)

__all__ = ["insert", "pan", "title", "zoom"]
