"""Overlay plugins: zoom, pan, insert (Phase 6).

Each overlay type occupies its own folder holding contract.py (classification + param validation +
registry entry) and ir.py (the pure to_ir facet). Importing this package registers every built-in
overlay into the default registry (the import side effect the kernel registry triggers lazily on
first use), so the registry stays the single source of truth -- exactly as the Layout plugins do.
"""

from videogen.plugins.overlays import insert, pan, zoom  # noqa: F401 -- import registers built-ins

__all__ = ["insert", "pan", "zoom"]
