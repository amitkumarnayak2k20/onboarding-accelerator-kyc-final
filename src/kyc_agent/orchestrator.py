import re
import time
from datetime import date, datetime
from .audit.store import (add_event, save_result, get_documents, get_application,
                         add_document, update_document_status, get_slo_counts)
from .observability.tracing import span
from .observability.metrics import (REQUESTS, REQUEST_LATENCY, MANUAL_REVIEW,
    APPLICATION_DECISIONS, DOCUMENTS_RECEIVED, ONBOARDING_SLO)
from .security.pii import redact_text
from .tools.document_extraction import extract_document_fields
from .tools.address_verification import verify_address
from .tools.risk_rating import assign_preliminary_risk
from .rag.vectorstore import search_knowledge


def _normalise(value):
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def _parse_date(value):
    if not value:
        return None
    value = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None


def expiry_check(value):
    if not value:
        return {"status": "NOT_CHECKED", "reason": "expiry_date_missing"}
    expiry = _parse_date(value)
    if not expiry:
        return {"status": "INVALID_FORMAT", "reason": "expiry_date_unparseable"}
    expired = expiry < date.today()
    return {"status": "EXPIRED" if expired else "VALID",
            "reason": "document_expired" if expired else "not_expired",
            "expiry_date_normalized": expiry.isoformat()}


def _field_match(expected, actual):
    if not expected or not actual:
        return {"status": "NOT_CHECKED", "match": None, "expected": expected, "extracted": actual}
    match = _normalise(expected) == _normalise(actual)
    return {"status": "MATCH" if match else "MISMATCH", "match": match,
            "expected": expected, "extracted": actual}


def process_application(applicant_id, request):
    started = time.perf_counter()
    with span("kyc.process_application", {"kyc.workflow": "account_opening", "applicant.id": applicant_id}):
        try:
            if request.document_text:
                _, redaction_counts = redact_text(request.document_text)
                stored = add_document(applicant_id, request.document_type, request.document_text, request.vendor_version)
                DOCUMENTS_RECEIVED.labels(request.document_type).inc()
                add_event(applicant_id, "DOCUMENT_RECEIVED", {"document_id": stored["document_id"],
                    "document_type": request.document_type, "vendor_version": request.vendor_version,
                    "pii_redaction_counts": redaction_counts})

            application = get_application(applicant_id)
            if not application:
                raise ValueError("Application not found")
            docs = [d for d in get_documents(applicant_id) if d["status"] != "SUPERSEDED"]
            if not docs:
                raise ValueError("No documents are registered. Submit at least one document before processing.")

            identity_types = {"passport", "driving_licence", "national_id"}
            if not any(d["document_type"] in identity_types for d in docs):
                raise ValueError("An identity document is required (passport, driving_licence or national_id).")

            per_doc, usage, missing, issues = [], [], [], []
            aggregate = {}
            identity_fields = None
            address_doc = None
            for doc in docs:
                try:
                    extracted = extract_document_fields(doc["document_text"], doc["document_type"])
                except Exception as exc:
                    add_event(applicant_id, "TOOL_EXECUTION_FAILED", {"tool": "extract_document_fields", "document_id": doc["document_id"], "error_type": type(exc).__name__})
                    raise
                fields = extracted["fields"]
                add_event(applicant_id, "TOOL_EXECUTION_COMPLETED", {"tool": "extract_document_fields", "document_id": doc["document_id"], "document_type": doc["document_type"], "fields_extracted": [k for k, v in fields.items() if v], "missing_required_fields": extracted["missing_required_fields"]})
                usage.append(extracted["usage"])
                for key, value in fields.items():
                    if value and not aggregate.get(key):
                        aggregate[key] = value
                if doc["document_type"] in identity_types and identity_fields is None:
                    identity_fields = fields
                if doc["document_type"] == "proof_of_address":
                    address_doc = fields
                expiry = expiry_check(fields.get("expiry_date")) if doc["document_type"] in identity_types else {"status": "NOT_APPLICABLE", "reason": "not_identity_document"}
                missing.extend(f"{doc['document_type']}:{field}" for field in extracted["missing_required_fields"])
                doc_status = "VERIFIED" if not extracted["missing_required_fields"] and expiry["status"] in ("VALID", "NOT_APPLICABLE") else "NEEDS_REVIEW"
                if expiry["status"] in ("EXPIRED", "INVALID_FORMAT"):
                    doc_status = "NEEDS_REVIEW"
                    issues.append({"code": "DOCUMENT_EXPIRED" if expiry["status"] == "EXPIRED" else "EXPIRY_DATE_INVALID",
                                   "document_id": doc["document_id"], "document_type": doc["document_type"], "field": "expiry_date"})
                update_document_status(doc["document_id"], doc_status)
                record = {"document_id": doc["document_id"], "document_type": doc["document_type"],
                          "status": doc_status, "extracted_fields": fields,
                          "missing_required_fields": extracted["missing_required_fields"],
                          "expiry_check": expiry, "vendor_version": doc["vendor_version"]}
                per_doc.append(record)
                add_event(applicant_id, "DOCUMENT_CHECK_COMPLETED", record)

            # Match identity claims against the applicant's submitted details.
            identity_checks = {}
            if identity_fields:
                identity_checks["full_name"] = _field_match(application.get("full_name"), identity_fields.get("full_name"))
                if identity_checks["full_name"]["match"] is False:
                    issues.append({"code": "NAME_MISMATCH", "field": "full_name",
                                   "applicant_value": application.get("full_name"),
                                   "document_value": identity_fields.get("full_name")})
                if application.get("date_of_birth"):
                    identity_checks["date_of_birth"] = _field_match(application.get("date_of_birth"), identity_fields.get("date_of_birth"))
                    # Compare semantically equivalent date formats (e.g. 18 April 1992 and 1992-04-18).
                    expected_date, actual_date = _parse_date(application.get("date_of_birth")), _parse_date(identity_fields.get("date_of_birth"))
                    if expected_date and actual_date:
                        identity_checks["date_of_birth"] = {"status": "MATCH" if expected_date == actual_date else "MISMATCH",
                            "match": expected_date == actual_date, "expected": expected_date.isoformat(), "extracted": actual_date.isoformat()}
                    if identity_checks["date_of_birth"]["match"] is False:
                        issues.append({"code": "DOB_MISMATCH", "field": "date_of_birth",
                                       "applicant_value": application.get("date_of_birth"),
                                       "document_value": identity_fields.get("date_of_birth")})
                else:
                    identity_checks["date_of_birth"] = {"status": "NOT_PROVIDED", "match": None}
                    issues.append({"code": "APPLICANT_DOB_NOT_PROVIDED", "field": "date_of_birth"})

            # Check the name on address evidence as well, where the document contains it.
            if address_doc and address_doc.get("full_name"):
                address_name = _field_match(application.get("full_name"), address_doc.get("full_name"))
                if address_name["match"] is False:
                    issues.append({"code": "ADDRESS_DOCUMENT_NAME_MISMATCH", "field": "full_name",
                                   "applicant_value": application.get("full_name"),
                                   "document_value": address_doc.get("full_name"), "document_type": "proof_of_address"})
            else:
                address_name = {"status": "NOT_CHECKED", "match": None}

            # Only an explicit proof-of-address document can satisfy address verification.
            # An address printed on an identity document is not treated as address proof.
            extracted_address = (address_doc or {}).get("address")
            try:
                address_result = verify_address(extracted_address, request.address_text or application.get("application_address"))
            except Exception as exc:
                add_event(applicant_id, "TOOL_EXECUTION_FAILED", {"tool": "verify_address", "error_type": type(exc).__name__})
                raise
            address_result["document_name_check"] = address_name
            add_event(applicant_id, "TOOL_EXECUTION_COMPLETED", {"tool": "verify_address", "result": address_result})
            if address_result.get("status") == "mismatch":
                issues.append({"code": "ADDRESS_MISMATCH", "field": "address",
                               "applicant_value": application.get("application_address"),
                               "document_value": extracted_address})
            elif address_result.get("status") == "inconclusive":
                issues.append({"code": "ADDRESS_NOT_VERIFIED", "field": "address"})

            # Reflect cross-document/applicant mismatches in the document inventory itself.
            mismatch_codes = {item["code"] for item in issues}
            if mismatch_codes.intersection({"NAME_MISMATCH", "DOB_MISMATCH"}):
                for item in per_doc:
                    if item["document_type"] in identity_types:
                        item["status"] = "NEEDS_REVIEW"
                        update_document_status(item["document_id"], "NEEDS_REVIEW")
            if mismatch_codes.intersection({"ADDRESS_MISMATCH", "ADDRESS_DOCUMENT_NAME_MISMATCH"}):
                for item in per_doc:
                    if item["document_type"] == "proof_of_address":
                        item["status"] = "NEEDS_REVIEW"
                        update_document_status(item["document_id"], "NEEDS_REVIEW")

            # The third tool is always called after extraction and address checks.
            try:
                risk = assign_preliminary_risk(aggregate, address_result, missing, issues=issues)
            except Exception as exc:
                add_event(applicant_id, "TOOL_EXECUTION_FAILED", {"tool": "assign_risk_rating", "error_type": type(exc).__name__})
                raise
            add_event(applicant_id, "TOOL_EXECUTION_COMPLETED", {"tool": "assign_risk_rating", "result": risk})
            if any(x["expiry_check"]["status"] in ("EXPIRED", "INVALID_FORMAT") for x in per_doc):
                risk["workflow_status"] = "MANUAL_REVIEW"
                risk["preliminary_risk_band"] = "HIGH"
                risk["reason_codes"] = sorted(set(risk["reason_codes"] + ["document_expired_or_invalid_expiry"]))

            policy = search_knowledge("account opening KYC document requirements address verification expiry and escalation guidance")
            inventory = [{"document_id": x["document_id"], "document_type": x["document_type"],
                          "status": x["status"], "vendor_version": x["vendor_version"]} for x in per_doc]
            result = {"applicant_id": applicant_id, "workflow_status": risk["workflow_status"],
                "decision": risk["workflow_status"], "document_inventory": inventory,
                "documents_checked": per_doc, "extracted_fields": aggregate,
                "identity_verification": identity_checks, "missing_required_fields": missing,
                "verification_issues": issues, "address_verification": address_result,
                "preliminary_assessment": risk,
                "tool_results": {"extract_document_fields": {"status": "COMPLETED", "documents_processed": len(per_doc)},
                    "verify_address": address_result, "assign_risk_rating": risk},
                "tools_executed": ["extract_document_fields", "verify_address", "assign_risk_rating"],
                "retrieved_policy_context": policy, "vendor_versions": sorted({x["vendor_version"] for x in docs}),
                "llm_usage": usage, "automated_checks_complete": True,
                "human_review_required": risk["requires_human_review"],
                "final_account_approval_required": True,
                "disclaimer": "Automated preliminary training assessment using configured rules and synthetic text documents. A passed pre-check is not final account-opening approval; production identity/authenticity checks and bank approval remain separate."}
            save_result(applicant_id, result)
            add_event(applicant_id, "APPLICATION_DECISION_RECORDED", {"workflow_status": risk["workflow_status"],
                "preliminary_risk_band": risk["preliminary_risk_band"], "documents_count": len(docs),
                "address_status": address_result["status"], "identity_checks": identity_checks,
                "verification_issues": issues, "tools_executed": result["tools_executed"]})
            APPLICATION_DECISIONS.labels(risk["workflow_status"]).inc()
            slo = get_slo_counts()
            if slo["slo_attainment"] is not None:
                ONBOARDING_SLO.set(slo["slo_attainment"])
            if risk["workflow_status"] in ("MANUAL_REVIEW", "NEEDS_MORE_INFORMATION"):
                MANUAL_REVIEW.labels(risk["workflow_status"]).inc()
            REQUESTS.labels("success").inc()
            return result
        except Exception as exc:
            REQUESTS.labels("failure").inc()
            add_event(applicant_id, "ONBOARDING_PROCESSING_FAILED", {"error_type": type(exc).__name__})
            raise
        finally:
            REQUEST_LATENCY.observe(time.perf_counter() - started)
