"""Portable immutability for frozen, slotted value objects.

``@dataclass(frozen=True, slots=True)`` does not reliably reject assignment of an
*unknown* attribute on CPython 3.12. The generated ``__setattr__`` is, in
substance::

    def __setattr__(self, name, value):
        if type(self) is cls or name in <field names>:
            raise FrozenInstanceError(...)
        super(cls, self).__setattr__(name, value)

``slots=True`` cannot add ``__slots__`` to an existing class, so dataclasses
builds a **new** class object and discards the original -- but the generated
method still closes over the *original* ``cls``. For a declared field the
``name in <field names>`` test short-circuits and the correct
``FrozenInstanceError`` is raised. For any other name the fall-through runs
``super(cls, self)`` with a ``cls`` the instance is not an instance of, and
CPython raises::

    TypeError: super(type, obj): obj must be an instance or subtype of type

The object is still not mutated either way, so this is an exception-type defect
rather than an immutability hole. It matters anyway: a governed result object
that fails with ``TypeError`` instead of ``FrozenInstanceError`` reports the
wrong reason, and the behaviour varies by interpreter patch level, so the same
code is not deterministic across supported 3.12 environments.

Dropping ``slots=True`` would fix the exception type but reintroduce
``__dict__``, which these result objects deliberately do not have -- an absent
``__dict__`` is what makes "no attribute can be added" structural rather than
merely enforced. Both properties are required, so neither can be traded away.

``immutable_value_object`` is applied *after* ``@dataclass`` and replaces the
generated accessors with ones that never consult the stale ``cls``. Order
matters::

    @immutable_value_object
    @dataclass(frozen=True, slots=True)
    class Result:
        ...

It cannot be written as a base class or inside the class body: ``@dataclass``
refuses to build a frozen class whose own ``__dict__`` already defines
``__setattr__``, and it overwrites an inherited one.

Construction is unaffected -- a frozen dataclass ``__init__`` assigns through
``object.__setattr__`` directly, never through the class's ``__setattr__`` -- and
``dataclasses.replace()``, equality, hashing, ``repr``, ``astuple``, pattern
matching, ``pickle`` and ``deepcopy`` all continue to work.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

__all__ = ["immutable_value_object"]


def immutable_value_object(cls):
    """Reject every attribute assignment and deletion with ``FrozenInstanceError``.

    Intended for ``@dataclass(frozen=True, slots=True)`` value objects whose
    immutability is part of a governed contract.
    """

    def __setattr__(self, name, value):  # noqa: N807
        raise FrozenInstanceError(f"cannot assign to field {name!r}")

    def __delattr__(self, name):  # noqa: N807
        raise FrozenInstanceError(f"cannot delete field {name!r}")

    cls.__setattr__ = __setattr__
    cls.__delattr__ = __delattr__
    return cls
