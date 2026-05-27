"""`insert` additive overlay: floating b-roll card (anchor/scale, painted by z) (Phase 6).

Importing the package registers the overlay into the default registry via its `contract` module.
"""

from videogen.plugins.overlays.insert import contract  # noqa: F401 -- import side effect: registers

__all__ = ["contract"]
