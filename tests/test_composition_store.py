"""CompositionStore: snapshot undo/redo + append-only journal (Phase 7, ADR 0001/0003).

The Composition is the source of truth (ADR 0003); the store holds it, lets an authoring loop undo
a regretted op by restoring a prior *snapshot* (not by replaying ops -- ADR 0001 rejects replay for
state), and keeps a separate append-only audit journal of what was applied. These tests assert that
externally observable behavior -- the document you get back after undo/redo, the journal's contents,
the disk round-trip -- never the store's internal stack or cursor layout. Snapshot equality is the
load-bearing guarantee: an undo must yield the *exact* prior document.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from videogen.kernel.composition import Composition
from videogen.stores.composition_store import CompositionStore


@pytest.fixture
def comp(host_only_composition: Callable[..., Composition]) -> Composition:
    return host_only_composition(src="host.mp4", duration=2.0)


def test_open_then_current_yields_the_opened_document(comp: Composition) -> None:
    store = CompositionStore()
    doc_id = store.open(comp)
    assert store.current(doc_id) == comp


def test_commit_advances_current_to_the_new_document(comp: Composition) -> None:
    store = CompositionStore()
    doc_id = store.open(comp)
    edited = comp.model_copy(update={"strict": False})

    store.commit(doc_id, edited, op="set_strict")

    assert store.current(doc_id) == edited


def test_undo_restores_the_exact_pre_op_document(comp: Composition) -> None:
    store = CompositionStore()
    doc_id = store.open(comp)
    store.commit(doc_id, comp.model_copy(update={"strict": False}), op="set_strict")

    restored = store.undo(doc_id)

    assert restored == comp  # the exact prior document, not a subtly different one
    assert store.current(doc_id) == comp


def test_redo_returns_to_the_post_op_document(comp: Composition) -> None:
    store = CompositionStore()
    doc_id = store.open(comp)
    edited = comp.model_copy(update={"strict": False})
    store.commit(doc_id, edited, op="set_strict")
    store.undo(doc_id)

    redone = store.redo(doc_id)

    assert redone == edited
    assert store.current(doc_id) == edited


def test_undo_is_isolated_from_later_external_mutation(comp: Composition) -> None:
    """A snapshot is a value, not a live ref: mutating the committed object can't corrupt it."""
    store = CompositionStore()
    doc_id = store.open(comp)
    edited = comp.model_copy(update={"strict": False})
    store.commit(doc_id, edited, op="set_strict")

    edited.strict = True  # mutate the object we handed in after committing it

    assert store.undo(doc_id).strict is True  # the base snapshot is unaffected
    assert store.redo(doc_id).strict is False  # the committed snapshot kept its value


def test_undo_past_the_beginning_stays_at_the_first_document(comp: Composition) -> None:
    store = CompositionStore()
    doc_id = store.open(comp)

    assert store.undo(doc_id) == comp  # nothing to undo: predictable no-op, not an error
    assert store.undo(doc_id) == comp
    assert store.current(doc_id) == comp


def test_redo_past_the_end_stays_at_the_last_document(comp: Composition) -> None:
    store = CompositionStore()
    doc_id = store.open(comp)
    edited = comp.model_copy(update={"strict": False})
    store.commit(doc_id, edited, op="set_strict")

    assert store.redo(doc_id) == edited  # nothing to redo: predictable no-op
    assert store.current(doc_id) == edited


def test_committing_after_undo_discards_the_redo_tail(comp: Composition) -> None:
    """Undo then commit forks history: the abandoned future is gone, the new branch is current."""
    store = CompositionStore()
    doc_id = store.open(comp)
    store.commit(doc_id, comp.model_copy(update={"strict": False}), op="first")
    store.undo(doc_id)  # back to the base

    branched = comp.model_copy(update={"version": 2})
    store.commit(doc_id, branched, op="second")

    assert store.current(doc_id) == branched
    assert store.redo(doc_id) == branched  # the old redo target is unreachable now


# --- the journal: append-only, in order, independent of undo (stories 12, 24, 25) ---


def test_journal_records_applied_ops_in_order(comp: Composition) -> None:
    store = CompositionStore()
    doc_id = store.open(comp)
    store.commit(doc_id, comp.model_copy(update={"strict": False}), op="set_strict")
    store.commit(doc_id, comp.model_copy(update={"version": 2}), op="bump_version")

    assert [e.op for e in store.journal(doc_id)] == ["set_strict", "bump_version"]


def test_undo_does_not_shorten_the_journal(comp: Composition) -> None:
    """Undo navigates snapshots; the audit trail is a separate, append-only structure."""
    store = CompositionStore()
    doc_id = store.open(comp)
    store.commit(doc_id, comp.model_copy(update={"strict": False}), op="set_strict")
    store.commit(doc_id, comp.model_copy(update={"version": 2}), op="bump_version")

    store.undo(doc_id)
    store.undo(doc_id)

    assert [e.op for e in store.journal(doc_id)] == ["set_strict", "bump_version"]  # intact


def test_commit_after_undo_still_appends_to_the_journal(comp: Composition) -> None:
    """The redo tail is discarded, but the journal keeps the full ordered history, undone work."""
    store = CompositionStore()
    doc_id = store.open(comp)
    store.commit(doc_id, comp.model_copy(update={"strict": False}), op="first")
    store.undo(doc_id)
    store.commit(doc_id, comp.model_copy(update={"version": 2}), op="second")

    assert [e.op for e in store.journal(doc_id)] == ["first", "second"]


# --- file persistence: durable across a process restart (stories 4, 26) ---


def test_store_round_trips_through_disk(comp: Composition, tmp_path: Path) -> None:
    store = CompositionStore()
    doc_id = store.open(comp)
    store.commit(doc_id, comp.model_copy(update={"strict": False}), op="set_strict")

    store.save(tmp_path / "store.json")
    reloaded = CompositionStore.load(tmp_path / "store.json")

    assert reloaded.current(doc_id) == store.current(doc_id)  # the document survived the restart
    assert [e.op for e in reloaded.journal(doc_id)] == ["set_strict"]  # so did the audit trail
