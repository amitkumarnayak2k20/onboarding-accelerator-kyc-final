from ..observability.metrics import TOOL_CALLS
from ..observability.tracing import span


def assign_preliminary_risk(fields: dict, address_result: dict, missing_fields: list[str], issues=None):
    """Transparent, deterministic training triage; not a regulated risk model."""
    with span("tool.assign_risk_rating", {"tool.name": "assign_risk_rating"}):
        issues = issues or []
        codes = [item.get("code", "verification_issue") for item in issues]
        if missing_fields:
            codes.append("required_document_fields_missing")
        if address_result.get("status") == "mismatch":
            codes.append("address_mismatch")
        if address_result.get("status") == "inconclusive":
            codes.append("address_not_verified")
        if any(code in codes for code in ("NAME_MISMATCH", "DOB_MISMATCH", "ADDRESS_DOCUMENT_NAME_MISMATCH", "ADDRESS_MISMATCH")):
            band, status = "HIGH", "MANUAL_REVIEW"
        elif codes:
            band, status = "MEDIUM", "NEEDS_MORE_INFORMATION"
        else:
            band, status = "LOW", "PRELIMINARY_KYC_PASSED"
        TOOL_CALLS.labels("assign_risk_rating", "success").inc()
        return {"preliminary_risk_band": band, "workflow_status": status,
                "reason_codes": sorted(set(codes)), "requires_human_review": status != "PRELIMINARY_KYC_PASSED"}
