"""Nimbus resource contracts.

Structure (types, required fields, no unknown fields) is enforced by pydantic here.
Semantic rules (value sets, code systems, plausibility, references) live in validation.py
so that every problem is reported with a stable Nimbus issue code.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Ref(Strict):
    """Reference to another resource by Nimbus id or by importer sourceKey ("Type/key")."""
    id: str | None = None
    sourceKey: str | None = None


class Coding(Strict):
    system: str
    code: str
    display: str | None = None


class CodeableConcept(Strict):
    coding: list[Coding] = Field(default_factory=list)
    text: str | None = None


class Identifier(Strict):
    system: str
    value: str


class HumanName(Strict):
    family: str
    given: list[str] = Field(default_factory=list)
    suffix: list[str] = Field(default_factory=list)
    use: str = "official"


class Address(Strict):
    lines: list[str] = Field(default_factory=list)
    city: str | None = None
    state: str | None = None
    postalCode: str | None = None
    country: str = "US"


class Telecom(Strict):
    system: str
    value: str
    use: str | None = None


class Period(Strict):
    start: datetime
    end: datetime | None = None


class Quantity(Strict):
    value: float
    unit: str
    comparator: str | None = None


# --- resources ---------------------------------------------------------------

class Organization(Strict):
    name: str
    type: str
    partOf: Ref | None = None
    identifiers: list[Identifier] = Field(default_factory=list)
    active: bool = True


class Location(Strict):
    name: str
    department: Ref
    active: bool = True


class Practitioner(Strict):
    name: HumanName
    npi: str | None = None
    billing: bool = False
    specialty: str
    active: bool = True
    identifiers: list[Identifier] = Field(default_factory=list)


class Payer(Strict):
    name: str
    identifiers: list[Identifier] = Field(default_factory=list)


class Plan(Strict):
    name: str
    payer: Ref
    planType: str | None = None


class Patient(Strict):
    identifiers: list[Identifier]
    name: HumanName
    otherNames: list[HumanName] = Field(default_factory=list)
    birthDate: date
    sexAtBirth: str
    genderIdentity: str | None = None
    race: list[str] = Field(default_factory=list)
    ethnicity: str | None = None
    address: list[Address] = Field(default_factory=list)
    telecom: list[Telecom] = Field(default_factory=list)
    noKnownAllergies: bool = False
    deceasedDate: date | None = None
    active: bool = True


class Coverage(Strict):
    patient: Ref
    payer: Ref
    plan: Ref
    memberId: str
    subscriberRelationship: str
    order: int = 1
    period: Period | None = None


class Encounter(Strict):
    patient: Ref
    encounterClass: str = Field(alias="class")
    status: str
    period: Period
    location: Ref | None = None
    practitioners: list[Ref] = Field(default_factory=list)
    reason: CodeableConcept | None = None

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Condition(Strict):
    patient: Ref
    encounter: Ref | None = None
    code: CodeableConcept
    clinicalStatus: str
    verificationStatus: str = "confirmed"
    onsetDate: date | None = None
    abatementDate: date | None = None
    note: str | None = None


class Reaction(Strict):
    manifestation: CodeableConcept
    severity: str | None = None


class AllergyIntolerance(Strict):
    patient: Ref
    substance: CodeableConcept
    codingStatus: str
    reactions: list[Reaction] = Field(default_factory=list)
    criticality: str
    recordedDate: date | None = None
    note: str | None = None


class Frequency(Strict):
    count: int
    period: float
    periodUnit: str


class Dosage(Strict):
    text: str | None = None
    doseQuantity: Quantity | None = None
    route: str | None = None
    frequency: Frequency | None = None
    asNeeded: bool = False
    asNeededReason: str | None = None
    durationDays: int | None = None


class MedicationRequest(Strict):
    patient: Ref
    encounter: Ref | None = None
    prescriber: Ref | None = None
    medication: CodeableConcept
    status: str
    authoredOn: date
    dosage: Dosage
    dosageStructured: bool


class ReferenceRange(Strict):
    low: float | None = None
    high: float | None = None
    text: str | None = None


class ObservationComponent(Strict):
    code: CodeableConcept
    valueQuantity: Quantity


class Observation(Strict):
    patient: Ref
    encounter: Ref | None = None
    category: str
    code: CodeableConcept
    status: str = "final"
    effective: datetime
    valueQuantity: Quantity | None = None
    valueCodeable: str | None = None
    valueString: str | None = None
    components: list[ObservationComponent] = Field(default_factory=list)
    referenceRange: ReferenceRange | None = None
    interpretation: str | None = None
    accession: str | None = None


class Immunization(Strict):
    patient: Ref
    vaccine: CodeableConcept
    occurrenceDate: date
    lotNumber: str | None = None
    performer: Ref | None = None


class DocumentReference(Strict):
    patient: Ref
    encounter: Ref | None = None
    author: Ref | None = None
    type: CodeableConcept
    date: datetime
    contentType: str
    content: str


class Appointment(Strict):
    patient: Ref
    practitioner: Ref | None = None
    location: Ref | None = None
    status: str
    start: datetime
    end: datetime
    reason: str | None = None


class ChargeItem(Strict):
    patient: Ref
    encounter: Ref
    code: CodeableConcept
    modifiers: list[str] = Field(default_factory=list)
    units: int = 1
    amount: float
    serviceDate: date


class UserAccount(Strict):
    username: str
    practitioner: Ref | None = None
    personName: HumanName
    active: bool = True


RESOURCE_MODELS: dict[str, type[Strict]] = {
    cls.__name__: cls
    for cls in [
        Organization, Location, Practitioner, Payer, Plan, Patient, Coverage, Encounter,
        Condition, AllergyIntolerance, MedicationRequest, Observation, Immunization,
        DocumentReference, Appointment, ChargeItem, UserAccount,
    ]
}


def dump(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json", by_alias=True, exclude_none=True)
