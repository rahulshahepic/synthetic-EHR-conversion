import pytest
from fastapi.testclient import TestClient

from nimbus.api import create_app
from nimbus.service import NimbusService
from nimbus.validation import npi_is_valid


@pytest.fixture
def client():
    return TestClient(create_app(NimbusService()))


def batch(client, rt, mode="commit"):
    r = client.post("/api/v1/import/batches", json={"resourceType": rt, "externalBatchId": "x", "mode": mode})
    assert r.status_code == 201, r.text
    return r.json()["batchId"]


def submit(client, bid, records):
    r = client.post(f"/api/v1/import/batches/{bid}/records", json={"records": records})
    assert r.status_code == 200, r.text
    return r.json()["results"]


def patient(mrn="1", **kw):
    p = {
        "identifiers": [{"system": "urn:halcyon:mrn:FAC1", "value": mrn}],
        "name": {"family": "Doe", "given": ["Jane"]},
        "birthDate": "1980-05-01",
        "sexAtBirth": "female",
    }
    p.update(kw)
    return p


def load_patient(client, key="P1", **kw):
    bid = batch(client, "Patient")
    res = submit(client, bid, [{"sourceKey": key, "resource": patient(**kw)}])
    assert res[0]["status"] == "accepted", res
    return bid, res[0]["targetId"]


def test_npi_check_digit():
    assert npi_is_valid("1234567893")
    assert not npi_is_valid("1234567890")


def test_valuesets_and_schema(client):
    assert "family-medicine" in client.get("/api/v1/meta/valuesets/specialty").json()["values"]
    assert "Patient" in client.get("/api/v1/meta/schema").json()


def test_patient_accept_reject_and_issue_codes(client):
    bid = batch(client, "Patient")
    res = submit(client, bid, [
        {"sourceKey": "ok", "resource": patient()},
        {"sourceKey": "badsex", "resource": patient(mrn="2", sexAtBirth="X")},
        {"sourceKey": "nodob", "resource": {k: v for k, v in patient(mrn="3").items() if k != "birthDate"}},
        {"sourceKey": "phone", "resource": patient(mrn="4", telecom=[{"system": "phone", "value": "555-1234"}])},
        {"sourceKey": "extra", "resource": patient(mrn="5", ssn="123")},
    ])
    codes = {r["sourceKey"]: [i["code"] for i in r["issues"]] for r in res}
    assert res[0]["status"] == "accepted"
    assert "E_VALUESET" in codes["badsex"]
    assert "E_REQUIRED" in codes["nodob"]
    assert "E_FORMAT" in codes["phone"]
    assert "E_UNKNOWN_FIELD" in codes["extra"]
    assert client.get(f"/api/v1/import/batches/{bid}").json()["counts"] == {"accepted": 1, "rejected": 4, "unchanged": 0}


def test_upsert_by_source_key_is_idempotent(client):
    _, pid = load_patient(client)
    bid = batch(client, "Patient")
    assert submit(client, bid, [{"sourceKey": "P1", "resource": patient()}])[0]["status"] == "unchanged"
    res = submit(client, bid, [{"sourceKey": "P1", "resource": patient(name={"family": "Smith", "given": ["Jane"]})}])
    assert res[0]["status"] == "accepted" and res[0]["targetId"] == pid
    got = client.get(f"/api/v1/Patient/{pid}").json()
    assert got["name"]["family"] == "Smith" and got["meta"]["version"] == 2
    assert client.get("/api/v1/Patient/$count").json()["total"] == 1


def test_duplicate_identity_rejected(client):
    load_patient(client)
    bid = batch(client, "Patient")
    res = submit(client, bid, [{"sourceKey": "P2", "resource": patient()}])
    assert res[0]["status"] == "rejected"
    assert res[0]["issues"][0]["code"] == "E_DUPLICATE_IDENTITY"


def test_reference_resolution_by_source_key(client):
    load_patient(client)
    bid = batch(client, "Condition")
    cond = {"code": {"coding": [{"system": "ICD-10-CM", "code": "E11.9"}]}, "clinicalStatus": "active"}
    res = submit(client, bid, [
        {"sourceKey": "C1", "resource": {**cond, "patient": {"sourceKey": "Patient/P1"}}},
        {"sourceKey": "C2", "resource": {**cond, "patient": {"sourceKey": "Patient/NOPE"}}},
        {"sourceKey": "C3", "resource": {**cond, "patient": {"sourceKey": "Practitioner/P1"}}},
    ])
    assert [r["status"] for r in res] == ["accepted", "rejected", "rejected"]
    assert res[1]["issues"][0]["code"] == "E_REF_UNRESOLVED"
    assert res[2]["issues"][0]["code"] == "E_REF_TYPE"
    stored = client.get(f"/api/v1/Condition/{res[0]['targetId']}").json()
    assert stored["patient"]["id"]


def test_condition_code_systems(client):
    load_patient(client)
    bid = batch(client, "Condition")
    base = {"patient": {"sourceKey": "Patient/P1"}, "clinicalStatus": "active"}
    res = submit(client, bid, [
        {"sourceKey": "icd9", "resource": {**base, "code": {"coding": [{"system": "ICD-9-CM", "code": "250.00"}]}}},
        {"sourceKey": "bad10", "resource": {**base, "code": {"coding": [{"system": "ICD-10-CM", "code": "250.00"}]}}},
        {"sourceKey": "text", "resource": {**base, "code": {"text": "bad back"}}},
        {"sourceKey": "textok", "resource": {**base, "code": {"text": "bad back"}, "verificationStatus": "unconfirmed"}},
    ])
    assert [r["status"] for r in res] == ["rejected", "rejected", "rejected", "accepted"]
    assert res[1]["issues"][0]["code"] == "E_CODE_FORMAT"


def test_vitals_plausibility_and_bp(client):
    load_patient(client)
    bid = batch(client, "Observation")
    base = {"patient": {"sourceKey": "Patient/P1"}, "category": "vital-signs", "effective": "2020-01-01T10:00:00-06:00"}
    wt = {"coding": [{"system": "LOINC", "code": "29463-7"}]}
    bp = {
        **base, "code": {"coding": [{"system": "LOINC", "code": "85354-9"}]},
        "components": [
            {"code": {"coding": [{"system": "LOINC", "code": "8480-6"}]}, "valueQuantity": {"value": 120, "unit": "mm[Hg]"}},
            {"code": {"coding": [{"system": "LOINC", "code": "8462-4"}]}, "valueQuantity": {"value": 80, "unit": "mm[Hg]"}},
        ],
    }
    res = submit(client, bid, [
        {"sourceKey": "w1", "resource": {**base, "code": wt, "valueQuantity": {"value": 80, "unit": "kg"}}},
        {"sourceKey": "w2", "resource": {**base, "code": wt, "valueQuantity": {"value": 1800, "unit": "[lb_av]"}}},
        {"sourceKey": "w3", "resource": {**base, "code": wt, "valueQuantity": {"value": 80, "unit": "lbs"}}},
        {"sourceKey": "notz", "resource": {**base, "effective": "2020-01-01T10:00:00", "code": wt, "valueQuantity": {"value": 80, "unit": "kg"}}},
        {"sourceKey": "bp", "resource": bp},
    ])
    assert [r["status"] for r in res] == ["accepted", "rejected", "rejected", "rejected", "accepted"]
    assert res[1]["issues"][0]["code"] == "E_PLAUSIBILITY"
    assert res[3]["issues"][0]["code"] == "E_TIMEZONE"


def test_nka_conflict(client):
    load_patient(client, noKnownAllergies=True)
    bid = batch(client, "AllergyIntolerance")
    res = submit(client, bid, [{"sourceKey": "A1", "resource": {
        "patient": {"sourceKey": "Patient/P1"}, "substance": {"text": "penicillin"},
        "codingStatus": "uncoded", "criticality": "high"}}])
    assert res[0]["issues"][0]["code"] == "E_CONFLICT"


def test_validate_only_does_not_write(client):
    bid = batch(client, "Patient", mode="validate-only")
    res = submit(client, bid, [{"sourceKey": "P1", "resource": patient()}])
    assert res[0]["status"] == "valid"
    assert client.get("/api/v1/Patient/$count").json()["total"] == 0


def test_org_hierarchy(client):
    bid = batch(client, "Organization")
    res = submit(client, bid, [
        {"sourceKey": "sys", "resource": {"name": "Riverbend", "type": "system"}},
        {"sourceKey": "site", "resource": {"name": "North", "type": "site", "partOf": {"sourceKey": "Organization/sys"}}},
        {"sourceKey": "dept", "resource": {"name": "Cardio", "type": "department", "partOf": {"sourceKey": "Organization/site"}}},
        {"sourceKey": "bad", "resource": {"name": "X", "type": "department", "partOf": {"sourceKey": "Organization/sys"}}},
        {"sourceKey": "orphan", "resource": {"name": "Y", "type": "site"}},
    ])
    assert [r["status"] for r in res] == ["accepted", "accepted", "accepted", "rejected", "rejected"]
    assert res[3]["issues"][0]["code"] == "E_HIERARCHY"


def test_rollback_create_and_update(client):
    b1, pid = load_patient(client)
    b2 = batch(client, "Patient")
    submit(client, b2, [
        {"sourceKey": "P1", "resource": patient(name={"family": "Changed", "given": []})},
        {"sourceKey": "P2", "resource": patient(mrn="2")},
    ])
    r = client.post(f"/api/v1/import/batches/{b2}/rollback")
    assert r.status_code == 200 and r.json()["status"] == "rolled_back"
    assert client.get("/api/v1/Patient/$count").json()["total"] == 1
    p = client.get(f"/api/v1/Patient/{pid}").json()
    assert p["name"]["family"] == "Doe" and p["meta"]["version"] == 1
    # idempotent
    assert client.post(f"/api/v1/import/batches/{b2}/rollback").json()["alreadyRolledBack"]
    # identifier index restored: P2's MRN is free again
    b3 = batch(client, "Patient")
    assert submit(client, b3, [{"sourceKey": "P3", "resource": patient(mrn="2")}])[0]["status"] == "accepted"


def test_rollback_refused_with_dependents_then_cascade(client):
    b1, _ = load_patient(client)
    b2 = batch(client, "Condition")
    submit(client, b2, [{"sourceKey": "C1", "resource": {
        "patient": {"sourceKey": "Patient/P1"}, "clinicalStatus": "active",
        "code": {"coding": [{"system": "ICD-10-CM", "code": "I10"}]}}}])
    r = client.post(f"/api/v1/import/batches/{b1}/rollback")
    assert r.status_code == 409
    assert r.json()["error"]["details"]["blockingBatches"] == [b2]
    r = client.post(f"/api/v1/import/batches/{b1}/rollback?cascade=true")
    assert r.status_code == 200 and set(r.json()["rolledBack"]) == {b1, b2}
    assert client.get("/api/v1/Condition/$count").json()["total"] == 0
    assert client.get("/api/v1/Patient/$count").json()["total"] == 0


def test_merge_and_rollback_merge(client):
    _, p1 = load_patient(client, key="P1", mrn="1")
    _, p2 = load_patient(client, key="P2", mrn="2", name={"family": "Doe", "given": ["Janet"]})
    b = batch(client, "Condition")
    c = submit(client, b, [{"sourceKey": "C1", "resource": {
        "patient": {"sourceKey": "Patient/P2"}, "clinicalStatus": "active",
        "code": {"coding": [{"system": "ICD-10-CM", "code": "I10"}]}}}])[0]["targetId"]
    mb = batch(client, "Patient")
    r = client.post(f"/api/v1/patients/{p1}/$merge", json={"sourcePatientId": p2, "importBatchId": mb})
    assert r.status_code == 200 and r.json()["movedReferences"] == 1
    assert client.get(f"/api/v1/Condition/{c}").json()["patient"]["id"] == p1
    assert client.get(f"/api/v1/Patient/{p2}").json()["active"] is False
    assert len(client.get(f"/api/v1/Patient/{p1}").json()["identifiers"]) == 2
    assert client.get("/api/v1/Patient/$count").json() == {"resourceType": "Patient", "total": 2, "active": 1}
    found = client.get("/api/v1/Patient", params={"identifier": "urn:halcyon:mrn:FAC1|2"}).json()["items"]
    assert {p["id"] for p in found} == {p1, p2}
    assert client.post(f"/api/v1/import/batches/{mb}/rollback").status_code == 200
    assert client.get(f"/api/v1/Condition/{c}").json()["patient"]["id"] == p2
    assert client.get(f"/api/v1/Patient/{p2}").json()["active"] is True


def test_search_by_patient(client):
    _, pid = load_patient(client)
    b = batch(client, "Condition")
    submit(client, b, [{"sourceKey": f"C{i}", "resource": {
        "patient": {"id": pid}, "clinicalStatus": "active",
        "code": {"coding": [{"system": "ICD-10-CM", "code": "I10"}]}}} for i in range(3)])
    assert len(client.get("/api/v1/Condition", params={"patient": pid}).json()["items"]) == 3


def test_closed_batch_rejects_writes(client):
    bid = batch(client, "Patient")
    client.post(f"/api/v1/import/batches/{bid}/close")
    r = client.post(f"/api/v1/import/batches/{bid}/records", json={"records": []})
    assert r.status_code == 409


def test_generic_user_and_charge_rules(client):
    b = batch(client, "UserAccount")
    res = submit(client, b, [{"sourceKey": "u", "resource": {"username": "FRONTDESK1", "personName": {"family": "Desk"}}}])
    assert res[0]["issues"][0]["code"] == "E_GENERIC_ACCOUNT"


def test_rollback_of_update_batch_not_blocked_by_earlier_references(client):
    load_patient(client)
    b2 = batch(client, "Condition")
    submit(client, b2, [{"sourceKey": "C1", "resource": {
        "patient": {"sourceKey": "Patient/P1"}, "clinicalStatus": "active",
        "code": {"coding": [{"system": "ICD-10-CM", "code": "I10"}]}}}])
    b3 = batch(client, "Patient")
    submit(client, b3, [{"sourceKey": "P1", "resource": patient(name={"family": "Renamed", "given": []})}])
    r = client.post(f"/api/v1/import/batches/{b3}/rollback")
    assert r.status_code == 200, r.text
    assert client.get("/api/v1/Condition/$count").json()["total"] == 1


def test_keyset_pagination_handles_equal_timestamps_and_legacy_offset(client):
    from bridge.load.client import NimbusClient

    bid = batch(client, "Patient")
    records = [{"sourceKey": f"P{i}", "resource": patient(mrn=str(i))} for i in range(1, 8)]
    assert all(r["status"] == "accepted" for r in submit(client, bid, records))
    service = client.app.state.service
    service._db.execute(
        "UPDATE resources SET created_at='2020-01-01T00:00:00+00:00' WHERE rtype='Patient'"
    )
    scanned = list(NimbusClient(client).iter_search("Patient", page_size=2))
    assert len(scanned) == 7
    assert len({r["id"] for r in scanned}) == 7
    assert [r["id"] for r in scanned] == sorted(r["id"] for r in scanned)
    assert all(r["meta"]["createdAt"] == "2020-01-01T00:00:00+00:00" for r in scanned)
    offset_page = client.get("/api/v1/Patient", params={"limit": 2, "offset": 2}).json()["items"]
    assert [r["id"] for r in offset_page] == [r["id"] for r in scanned[2:4]]
    invalid = client.get("/api/v1/Patient", params={"afterCreatedAt": "2020-01-01"})
    assert invalid.status_code == 400


def test_repeated_parent_reference_uses_batch_local_cache(client):
    load_patient(client, key="P1")
    service = client.app.state.service
    original = service._row_by_sk
    calls = []

    def tracked(rt, sk):
        if (rt, sk) == ("Patient", "P1"):
            calls.append(sk)
        return original(rt, sk)

    service._row_by_sk = tracked
    bid = batch(client, "Condition")
    base = {
        "patient": {"sourceKey": "Patient/P1"},
        "code": {"coding": [{"system": "ICD-10-CM", "code": "E11.9"}]},
        "clinicalStatus": "active",
    }
    results = submit(client, bid, [
        {"sourceKey": f"C{i}", "resource": base} for i in range(8)
    ])
    assert all(r["status"] == "accepted" for r in results)
    assert len(calls) == 1


def test_search_match_filters_top_level_fields(client):
    from bridge.load.client import NimbusClient

    bid = batch(client, "Patient")
    records = [{"sourceKey": f"P{i}", "resource": patient(mrn=str(i), sexAtBirth=sex)}
               for i, sex in enumerate(["female", "male", "female", "unknown", "male"], 1)]
    assert all(r["status"] == "accepted" for r in submit(client, bid, records))
    nc = NimbusClient(client)
    assert sorted(r["sourceKey"] for r in nc.iter_search("Patient", page_size=1, match={"sexAtBirth": ["female"]})) == ["P1", "P3"]
    both = nc.iter_search("Patient", page_size=2, match={"sexAtBirth": ["female", "unknown"], "active": ["x"]})
    assert list(both) == []  # every field must match; non-string fields never equal a string value
    assert len(list(nc.iter_search("Patient", match={"sexAtBirth": ["female", "unknown"]}))) == 3
    bad = client.get("/api/v1/Patient", params={"match": "sexAtBirth"})
    assert bad.status_code == 400
    bad = client.get("/api/v1/Patient", params={"match": "data') OR 1=1 --:x"})
    assert bad.status_code == 400
