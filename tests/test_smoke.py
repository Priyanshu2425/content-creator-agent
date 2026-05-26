"""Phase 0 smoke test: the package imports.

Proves pytest discovers tests under tests/, the src/ layout resolves, and the
package is installed into the environment -- the externally observable behavior
of the scaffold. There is no domain logic to test yet.
"""

from __future__ import annotations


def test_package_imports() -> None:
    import videogen
    import videogen.kernel

    assert videogen.__name__ == "videogen"
    assert videogen.kernel.__name__ == "videogen.kernel"
