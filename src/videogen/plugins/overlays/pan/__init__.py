"""`pan` transform overlay (Phase 6).

Importing the package registers the overlay into the default registry via its `contract` module.
"""

from videogen.plugins.overlays.pan import contract  # noqa: F401 -- import side effect: registers

__all__ = ["contract"]
