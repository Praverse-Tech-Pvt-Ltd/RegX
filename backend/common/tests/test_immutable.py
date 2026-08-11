"""Portability contract for frozen, slotted value objects.

Database-free. These tests state the contract directly on a local dataclass, so
the guarantee is pinned independently of any domain result type that relies on
it, and a future interpreter change is caught here rather than through a
confusing failure in a governed service suite.
"""

from __future__ import annotations

import copy
import dataclasses
import pickle
from dataclasses import FrozenInstanceError, dataclass

import pytest

from common.immutable import immutable_value_object


@immutable_value_object
@dataclass(frozen=True, slots=True)
class Guarded:
    a: int = 1
    b: str = "x"


@dataclass(frozen=True, slots=True)
class Unguarded:
    a: int = 1
    b: str = "x"


class TestImmutabilityContract:
    def test_an_existing_field_cannot_be_reassigned(self):
        obj = Guarded()
        for field in dataclasses.fields(obj):
            with pytest.raises(FrozenInstanceError):
                setattr(obj, field.name, None)

    def test_a_new_attribute_cannot_be_added(self):
        """The case a bare frozen+slots dataclass gets wrong on CPython 3.12."""
        with pytest.raises(FrozenInstanceError):
            Guarded().injected = 1

    def test_an_attribute_cannot_be_deleted(self):
        with pytest.raises(FrozenInstanceError):
            del Guarded().a

    def test_the_instance_has_no_dict(self):
        # Structural, not merely enforced: there is nowhere to put an attribute.
        assert not hasattr(Guarded(), "__dict__")
        assert Guarded.__slots__ == ("a", "b")

    def test_values_remain_readable(self):
        obj = Guarded(a=5, b="y")
        assert (obj.a, obj.b) == (5, "y")


class TestDefectItGuardsAgainst:
    """Pins the exact upstream behaviour, so the guard is not cargo-culted.

    If a future interpreter fixes the underlying defect this test fails loudly,
    which is the signal to reconsider the decorator -- rather than leaving it in
    place forever with nobody remembering why.
    """

    def test_a_bare_frozen_slots_dataclass_rejects_a_known_field_correctly(self):
        with pytest.raises(FrozenInstanceError):
            Unguarded().a = 2

    def test_a_bare_frozen_slots_dataclass_does_not_raise_frozen_error_for_a_new_name(self):
        # The generated __setattr__ falls through to super(cls, self) with the
        # pre-slots cls, so this is a TypeError rather than FrozenInstanceError.
        # The object is still not mutated -- only the reported reason is wrong.
        obj = Unguarded()
        with pytest.raises(TypeError):
            obj.injected = 1
        assert not hasattr(obj, "injected")


class TestDataclassBehaviourIsUnaffected:
    """The guard must not cost anything a frozen dataclass normally provides."""

    def test_construction_and_fields(self):
        obj = Guarded(a=5, b="y")
        assert [f.name for f in dataclasses.fields(obj)] == ["a", "b"]

    def test_replace_equality_hash_and_repr(self):
        obj = Guarded(a=5, b="y")
        assert dataclasses.replace(obj, a=7) == Guarded(a=7, b="y")
        assert Guarded(1, "x") == Guarded(1, "x")
        assert hash(Guarded(1, "x")) == hash(Guarded(1, "x"))
        assert "Guarded(a=5" in repr(obj)

    def test_pickle_and_deepcopy_round_trip(self):
        obj = Guarded(a=5, b="y")
        assert pickle.loads(pickle.dumps(obj)) == obj
        assert copy.deepcopy(obj) == obj

    def test_pattern_matching_still_works(self):
        match Guarded(a=5, b="y"):
            case Guarded(a=5):
                matched = True
            case _:
                matched = False
        assert matched

    def test_a_guarded_subclass_keeps_the_contract(self):
        @immutable_value_object
        @dataclass(frozen=True, slots=True)
        class Child(Guarded):
            c: float = 0.0

        child = Child()
        with pytest.raises(FrozenInstanceError):
            child.injected = 1
        assert not hasattr(child, "__dict__")
