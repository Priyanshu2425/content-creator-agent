"""CompositionStore: snapshot undo/redo + append-only audit journal (Phase 7, ADR 0001/0003).

The Composition is the source of truth (ADR 0003); the store holds it in memory keyed by document
id, with file persistence so it survives a process restart. Two intentionally distinct structures
back each document, per the project's persistence decision:

- A **snapshot undo/redo stack** with a cursor. Undo restores a prior whole-document snapshot rather
  than replaying ops in reverse -- ADR 0001 rejects replay for runtime state, and recovery follows
  the same instinct (restoring a snapshot is total and order-independent). Snapshots are full
  Composition values round-tripped through JSON (the Phase 1 serialization), so an undo yields the
  *exact* prior document and is isolated from later mutation of the object that was committed.
- An **append-only audit journal**: the ordered record of which ops were applied. It is never
  shortened -- undo navigates the snapshot cursor but does not touch the journal -- so the full
  authoring history (including work later undone) stays auditable. Conflating the two would lose
  that trail on undo, which is why they are separate.

This is the durable write surface the Builder/AuthoringService will write through in Phase 8; here
it stands alone and is exercised directly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from videogen.kernel.composition import Composition


@dataclass(frozen=True)
class JournalEntry:
    """One append-only audit record: an op applied, in order (``seq`` is its 0-based position)."""

    seq: int
    op: str


@dataclass
class _Document:
    """One document's snapshot stack (+ cursor) and its separate append-only journal."""

    snapshots: list[Composition]
    cursor: int = 0
    journal: list[JournalEntry] = field(default_factory=list)


def _snapshot(composition: Composition) -> Composition:
    """A defensive, isolated copy of a Composition via the Phase 1 JSON round-trip."""
    return Composition.model_validate(composition.model_dump(by_alias=True))


class CompositionStore:
    """In-memory Compositions keyed by id: snapshot undo/redo, journal, and file persistence."""

    def __init__(self) -> None:
        self._docs: dict[str, _Document] = {}
        self._next_id = 0

    def open(self, composition: Composition, *, doc_id: str | None = None) -> str:
        """Register a Composition as a new document (its first snapshot); return its id."""
        if doc_id is None:
            doc_id = f"doc-{self._next_id}"
            self._next_id += 1
        self._docs[doc_id] = _Document(snapshots=[_snapshot(composition)])
        return doc_id

    def current(self, doc_id: str) -> Composition:
        """The document's current snapshot (where the undo cursor sits)."""
        doc = self._docs[doc_id]
        return _snapshot(doc.snapshots[doc.cursor])

    def commit(self, doc_id: str, composition: Composition, *, op: str) -> None:
        """Record ``composition`` as the new current snapshot and append ``op`` to the journal.

        Committing after an undo discards the redo tail (the abandoned future), but the journal --
        append-only -- keeps growing regardless, so the audit trail is never rewritten.
        """
        doc = self._docs[doc_id]
        del doc.snapshots[doc.cursor + 1 :]
        doc.snapshots.append(_snapshot(composition))
        doc.cursor = len(doc.snapshots) - 1
        doc.journal.append(JournalEntry(seq=len(doc.journal), op=op))

    def undo(self, doc_id: str) -> Composition:
        """Move the cursor back one snapshot and return it; a no-op at the beginning."""
        doc = self._docs[doc_id]
        if doc.cursor > 0:
            doc.cursor -= 1
        return _snapshot(doc.snapshots[doc.cursor])

    def redo(self, doc_id: str) -> Composition:
        """Move the cursor forward one snapshot and return it; a no-op at the end."""
        doc = self._docs[doc_id]
        if doc.cursor < len(doc.snapshots) - 1:
            doc.cursor += 1
        return _snapshot(doc.snapshots[doc.cursor])

    def journal(self, doc_id: str) -> tuple[JournalEntry, ...]:
        """The append-only, in-order record of ops applied to the document."""
        return tuple(self._docs[doc_id].journal)

    # --- file persistence: the whole store (snapshots, cursors, journals) survives a restart ---

    def save(self, path: str | Path) -> None:
        """Flush the in-memory store to a JSON file (the Composition's Phase 1 serialization)."""
        payload = {
            "next_id": self._next_id,
            "docs": {
                doc_id: {
                    "snapshots": [s.model_dump(by_alias=True) for s in doc.snapshots],
                    "cursor": doc.cursor,
                    "journal": [{"seq": e.seq, "op": e.op} for e in doc.journal],
                }
                for doc_id, doc in self._docs.items()
            },
        }
        Path(path).write_text(json.dumps(payload))

    @classmethod
    def load(cls, path: str | Path) -> CompositionStore:
        """Reconstruct a store from a file written by :meth:`save`."""
        payload = json.loads(Path(path).read_text())
        store = cls()
        store._next_id = payload["next_id"]
        for doc_id, raw in payload["docs"].items():
            store._docs[doc_id] = _Document(
                snapshots=[Composition.model_validate(s) for s in raw["snapshots"]],
                cursor=raw["cursor"],
                journal=[JournalEntry(seq=e["seq"], op=e["op"]) for e in raw["journal"]],
            )
        return store
