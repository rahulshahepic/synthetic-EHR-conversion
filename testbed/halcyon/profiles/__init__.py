"""Source profiles: the conventions of one Halcyon source system, as data.

A *profile* bundles everything that makes one source system look like itself:
which facilities exist and what units they chart in, the local visit-type
codes, lab unit conventions, and the sig-writing habits of its prescribers.
The generator reads the *active* profile (``Config.profile``) instead of the
raw ``vocab`` globals, so a run can be generated under a different source's
conventions — e.g. to exercise Bridge's drift monitors when the feed a run is
watching starts arriving in another facility's style (T-108).

Adding a profile (for the next facility system someone invents):

1. Create ``profiles/<name>.py`` defining the tables below and a module-level
   ``FacilityProfile`` instance. Lab overrides and sig variants replace whole
   rows from ``vocab``: a lab override is a full ``vocab.LABS``-shaped tuple
   expressed in the profile's own units *and* numeric ranges, so a value's
   unit and its scale can never drift apart. A sig variant replaces the whole
   sig list for one formulary code.
2. Register it in ``PROFILES`` in this module.
3. Select it with ``Config(profile="<name>")``, ``generate(..., profile=...)``,
   or ``python -m testbed.halcyon generate --profile <name>``.

Invariants:

- The ``default`` profile wraps the ``vocab`` constants unchanged, and the
  generator's code paths for it consume the RNG exactly as they did before
  profiles existed: default output is byte-identical for a given seed.
  Golden tests in ``tests/testbed/test_halcyon_profiles.py`` pin this.
- Visit types carry a *truth class* (ambulatory / emergency / inpatient /
  observation / virtual / None) next to each local code. Generator behavior
  (vitals, notes, charges, discharge, department routing) keys off the class,
  so a profile's local codes can be anything — including an uncoded/unknown
  code whose class is None (``unknown_visit_code``).
- All data stays synthetic; profiles only reshuffle invented conventions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .. import vocab as V

# How the generator routes a visit to a department, keyed by truth class.
# Codes missing here fall back to a random clinic of the visit's facility.
DEFAULT_CLASS_DEPTS = {"emergency": "D100", "inpatient": "D110", "observation": "D110", "virtual": "D910"}


@dataclass(frozen=True)
class FacilityProfile:
    """One source system's conventions. See the module docstring."""

    name: str
    # MSH-4 sending-facility label in the HL7 feeds.
    sender: str
    # vocab.FACILITIES-shaped rows: (id, name, tz, weight unit, temp unit, height unit).
    facilities: tuple[tuple[str, ...], ...]
    # vocab.DEPTS-shaped rows: (id, facility id or None if shared, name, kind).
    depts: tuple[tuple[str, ...], ...]
    # (facility id, weight) for a person's home facility; weights expand to a
    # choice list, exactly like the historical hard-coded pick.
    facility_weights: tuple[tuple[str, int], ...]
    # local visit code -> (truth class, sampling weight); class None = uncoded.
    visit_types: dict[str, tuple[str | None, int]]
    # The profile's uncoded/unknown visit code (planted by the visit_xx rate).
    unknown_visit_code: str
    # Truth class -> department id for visit routing.
    class_depts: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_CLASS_DEPTS))
    # Lab code -> full vocab.LABS-shaped row in this profile's conventions.
    lab_overrides: dict[str, tuple[Any, ...]] = field(default_factory=dict)
    # Formulary code -> replacement sig list, in this profile's house style.
    sig_variants: dict[str, list[str]] = field(default_factory=dict)
    # Config.rates key -> value; merged over the defaults when selected.
    rates: dict[str, float] = field(default_factory=dict)
    # manifest.json "notes" block, describing this system's conventions.
    manifest_notes: dict[str, str] = field(default_factory=dict)

    def lab(self, code: str) -> tuple[Any, ...]:
        """The effective LABS row for `code` under this profile."""
        return self.lab_overrides.get(code, V.LABS[code])

    def sigs(self, code: str, default: list[str]) -> list[str]:
        """The sig list for a formulary code under this profile."""
        return self.sig_variants.get(code, default)


DEFAULT_PROFILE = FacilityProfile(
    name="default",
    sender="RIVERBEND",
    facilities=tuple(V.FACILITIES),
    depts=tuple(V.DEPTS),
    facility_weights=(("FAC1", 2), ("FAC2", 1), ("FAC3", 1)),
    visit_types=V.VISIT_TYPES,
    unknown_visit_code="XX",
    manifest_notes={
        "timestamps": "Facility local time, no offset. FAC1/FAC2 US Central, FAC3 US Mountain.",
        "units": "VITALS have no unit columns; FAC1/FAC2 record lb/degF/in, FAC3 kg/degC/cm.",
        "charges": "AMOUNT is dollars (with decimals) before 2012-01-01, integer cents after.",
        "feeds": "HL7 v2.3. ADT A08 newer than PAT; A40 = merge (MRG = retired MRN). ORU: last 30 days only in feed.",
    },
)

from .lakeside import LAKESIDE_PROFILE  # noqa: E402  (needs FacilityProfile defined above)

PROFILES: dict[str, FacilityProfile] = {p.name: p for p in (DEFAULT_PROFILE, LAKESIDE_PROFILE)}


def get_profile(name: str) -> FacilityProfile:
    try:
        return PROFILES[name]
    except KeyError:
        raise ValueError(f"unknown halcyon profile {name!r}; known: {', '.join(sorted(PROFILES))}") from None
