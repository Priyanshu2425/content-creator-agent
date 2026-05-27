"""Layout plugins: named region arrangements (full, split_h, ...) (Phase 5).

Each layout occupies its own folder defining its region slots + geometry. Importing this package
registers every built-in Layout into the default registry (the import side effect the kernel
registry triggers lazily on first use), so the registry stays the single source of truth.
"""

from videogen.plugins.layouts import full, split_h  # noqa: F401 -- import registers the built-ins

__all__ = ["full", "split_h"]
