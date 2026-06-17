"""`title` additive overlay: the static text hook headline (texthook/01).

Importing the package registers the overlay into the default registry via its `contract` module.
"""

from videogen.plugins.overlays.title import contract  # noqa: F401 -- import side effect: registers

__all__ = ["contract"]
