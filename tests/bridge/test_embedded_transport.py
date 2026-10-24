"""Embedded Nimbus transport should reuse its AnyIO portal across API calls."""

from bridge.load.client import connect


def test_embedded_client_reuses_portal_and_preserves_api():
    client = connect("embedded::memory:")
    portal = client.http.portal
    assert portal is not None
    assert client.count("Patient")["total"] == 0
    batch = client.create_batch("Patient", "portal-smoke")
    assert batch.startswith("nb-")
    assert client.close(batch)["status"] == "closed"
    assert client.http.portal is portal
