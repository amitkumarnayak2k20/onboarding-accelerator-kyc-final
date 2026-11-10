from dataclasses import replace
from fastapi.testclient import TestClient
from kyc_agent import api
from kyc_agent.config import settings
from kyc_agent.audit import store as audit_store


def test_inventory_process_and_duplicate_request_guard(tmp_path, monkeypatch):
    db = tmp_path / "workflow.sqlite"
    monkeypatch.setattr(audit_store, "settings", replace(settings, database_path=str(db)))
    client = TestClient(api.app)

    created = client.post("/applications", json={
        "applicant_id": "workflow-001",
        "full_name": "Asha Rao",
        "application_address": "12 Sample Road, Hyderabad, Telangana, 500001"
    })
    assert created.status_code == 201

    submitted = client.post("/applications/workflow-001/documents", json={
        "document_type": "passport",
        "vendor_version": "ocr-v1",
        "document_text": (
            "Name: Asha Rao\nDate of Birth: 1990-06-15\n"
            "Document Number: P1234567\nExpiry Date: 2030-06-15\n"
            "Address: 12 Sample Road, Hyderabad, Telangana, 500001"
        )
    })
    assert submitted.status_code == 201

    inventory = client.get("/applications/workflow-001/documents").json()
    assert len(inventory["documents"]) == 1
    assert "document_text" not in inventory["documents"][0]

    processed = client.post("/applications/workflow-001/process", json={})
    assert processed.status_code == 200
    assert processed.json()["documents_checked"][0]["status"] == "VERIFIED"
    assert processed.json()["human_review_required"] is True
    assert processed.json()["address_verification"]["status"] == "inconclusive"

    request = client.post("/applications/workflow-001/document-requests", json={
        "document_type": "passport", "reason": "Passport copy requested"
    })
    assert request.status_code == 200
    assert request.json()["sent_to_customer"] is False
    assert request.json()["request"]["status"] == "BLOCKED_DUPLICATE"

    audit = client.get("/applications/workflow-001/audit").json()["events"]
    event_types = [e["event_type"] for e in audit]
    assert "DOCUMENT_RECEIVED" in event_types
    assert "DOCUMENT_CHECK_COMPLETED" in event_types
    assert "APPLICATION_DECISION_RECORDED" in event_types
    assert "DUPLICATE_DOCUMENT_REQUEST_BLOCKED" in event_types

    slo = client.get("/slo/summary").json()
    assert slo["applications_with_decision"] == 1
    assert slo["slo_attainment"] == 1.0


def test_process_requires_a_submitted_document(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_store, "settings", replace(settings, database_path=str(tmp_path / "empty.sqlite")))
    client = TestClient(api.app)
    client.post("/applications", json={"applicant_id": "empty-001", "full_name": "Test User"})
    response = client.post("/applications/empty-001/process", json={})
    assert response.status_code == 400
    assert "Submit at least one document" in response.json()["detail"]


def test_identity_document_required(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_store, "settings", replace(settings, database_path=str(tmp_path / "no-id.sqlite")))
    client = TestClient(api.app)
    client.post("/applications", json={"applicant_id": "no-id-001", "full_name": "Test User"})
    client.post("/applications/no-id-001/documents", json={
        "document_type": "proof_of_address",
        "document_text": "Name: Test User\nAddress: 1 Sample Road, Hyderabad"
    })
    response = client.post("/applications/no-id-001/process", json={})
    assert response.status_code == 400
    assert "identity document is required" in response.json()["detail"]


def test_automated_three_tool_verification_and_name_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_store, "settings", replace(settings, database_path=str(tmp_path / "matching.sqlite")))
    client = TestClient(api.app)
    address = "Flat 402, Lakeview Residency, Road No. 12, Jubilee Hills, Hyderabad, Telangana 500033"
    client.post("/applications", json={
        "applicant_id": "match-001", "full_name": "Rohan Mehta",
        "date_of_birth": "1992-04-18", "application_address": address
    })
    client.post("/applications/match-001/documents", json={
        "document_type": "driving_licence",
        "document_text": "Name: Rohan Mehta\nDate of birth: 18 April 1992\nLicence number: MOCK-123\nExpiry date: 11 January 2044\nAddress: " + address
    })
    client.post("/applications/match-001/documents", json={
        "document_type": "proof_of_address",
        "document_text": "Customer name: Rohan Mehta\nService address: " + address
    })
    result = client.post("/applications/match-001/process", json={}).json()
    assert result["workflow_status"] == "PRELIMINARY_KYC_PASSED"
    assert result["human_review_required"] is False
    assert result["identity_verification"]["full_name"]["match"] is True
    assert result["identity_verification"]["date_of_birth"]["match"] is True
    assert result["address_verification"]["match"] is True
    assert result["tools_executed"] == ["extract_document_fields", "verify_address", "assign_risk_rating"]
    audit_types = [e["event_type"] for e in client.get("/applications/match-001/audit").json()["events"]]
    assert audit_types.count("TOOL_EXECUTION_COMPLETED") >= 4

    changed = client.patch("/applications/match-001", json={"full_name": "Ajay Kumar Nayak"})
    assert changed.status_code == 200
    assert changed.json()["status"] == "UPDATED_AND_REVERIFIED"
    verification = changed.json()["verification"]
    assert verification["workflow_status"] == "MANUAL_REVIEW"
    assert any(x["code"] == "NAME_MISMATCH" for x in verification["verification_issues"])


def test_mock_extractor_supports_driving_licence_labels():
    from kyc_agent.llm.provider import _mock_extract
    fields = _mock_extract(
        "Name: Rohan Mehta\nDate of birth: 18 April 1992\n"
        "Licence number: MOCK-123\nExpiry date: 11 January 2044\n"
        "Address: 1 Sample Road, Hyderabad"
    )
    assert fields["full_name"] == "Rohan Mehta"
    assert fields["date_of_birth"] == "18 April 1992"
    assert fields["document_number"] == "MOCK-123"
    assert fields["expiry_date"] == "11 January 2044"
