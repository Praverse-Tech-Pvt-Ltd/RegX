"""Which dosage forms are solid, for the per-volume rule on formulation components.

A component of a tablet or capsule cannot sensibly be stated per volume
(mg/5mL) or as a w/v or v/v percentage: there is no volume to be "per". Such an
amount could only ever meet an IID limit of the same per-volume basis, which
belongs to liquid products, so the comparison would look like-for-like when it
is not. The amount is therefore refused (not merely warned about) on a product
whose dosage form is clearly solid.

"Clearly solid" is deliberately narrow: the product's dosage form (free text)
names a solid unit such as TABLET, CAPSULE, POWDER, GRANULE, FILM or PATCH, and
does not say it is made into a liquid before use ("... FOR SUSPENSION", "... FOR
SOLUTION", "... FOR INJECTION"), where a per-volume amount after reconstitution is legitimate. A
blank or unknown dosage form is never treated as solid.
"""

from __future__ import annotations

import re

SOLID_WORDS = (
    "TABLET",
    "TABLETS",
    "CAPSULE",
    "CAPSULES",
    "CAPLET",
    "LOZENGE",
    "TROCHE",
    "PASTILLE",
    "PELLET",
    "PELLETS",
    "IMPLANT",
    "SUPPOSITORY",
    "WAFER",
    "GUM",
    # QA-19: a plain powder or granule has no volume either. "POWDER, FOR
    # SOLUTION" and the like stay liquid through _MADE_INTO_LIQUID below.
    "POWDER",
    "POWDERS",
    "GRANULE",
    "GRANULES",
    # QA-19 follow-up: the other clearly solid SPL dosage forms (26 SPL terms;
    # the full list outcome is pinned in tests/test_qa19_per_volume_on_solid_forms.py).
    # Not here on purpose: a liquid on a carrier (CLOTH, SWAB, DRESSING),
    # semi-solids (CREAM, GEL, PASTE, POULTICE, ...) and non-forms (KIT, SYSTEM).
    "BAR",
    "BEAD",
    "CHEWABLE",
    "CRYSTAL",
    "DISC",
    "FIBER",
    "FILM",
    "GLOBULE",
    "INSERT",
    "LENS",
    "DEVICE",
    "LIPSTICK",
    "PATCH",
    "PILL",
    "PLASTER",
    "RING",
    "SPONGE",
    "STICK",
    "STRIP",
    "TAMPON",
    "TAPE",
)
#: "FOR SOLUTION", "FOR ORAL SUSPENSION", "FOR LIPOSOMAL SUSPENSION", "FOR INJECTION":
#: made into a liquid before use. One optional qualifier word is allowed so the
#: SPL term "INJECTION, POWDER, LYOPHILIZED, FOR LIPOSOMAL SUSPENSION" reads as
#: reconstituted (tests: the full SPL list, test_qa19_per_volume_on_solid_forms).
_MADE_INTO_LIQUID = re.compile(r"\bFOR\s+(?:[A-Z]+\s+)?(SUSPENSION|SOLUTION|INJECTION)\b")

#: Bases that need a volume to be relative to.
PER_VOLUME_BASES = ("per_volume", "w_v", "v_v")


def is_solid_dosage_form(dosage_form: str | None) -> bool:
    text = (dosage_form or "").upper()
    if not text.strip() or _MADE_INTO_LIQUID.search(text):
        return False
    words = set(re.findall(r"[A-Z]+", text))
    return any(word in words for word in SOLID_WORDS)


def per_volume_on_solid_problem(dosage_form: str | None, expression) -> str | None:
    """None unless a per-volume meaning is stated for a component of a solid product."""
    if expression is None or expression.basis not in PER_VOLUME_BASES:
        return None
    if not is_solid_dosage_form(dosage_form):
        return None
    return (
        f"'{expression}' is an amount per volume, but this product's dosage form is "
        f"{dosage_form.strip()}, a solid. State the amount per dosage unit (or as % w/w); "
        "if the product is made into a liquid before use, record that in its dosage form."
    )
