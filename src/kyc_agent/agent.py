import re, os
from .audit.store import (list_applications, get_application, get_documents, get_document_requests,
                          update_application, add_event)
from .rag.vectorstore import search_knowledge
from .orchestrator import process_application
from .schemas import ProcessRequest

APP_ID_RE = re.compile(r"\b(?:application|app)\s*(?:id)?\s*[:#-]?\s*([A-Za-z0-9_-]{3,64})\b", re.I)
KNOWN_ID_RE = re.compile(r"\b(APP[-_][A-Za-z0-9_-]+|KYC[-_][A-Za-z0-9_-]+)\b", re.I)


def _extract_id(message: str):
    m=KNOWN_ID_RE.search(message) or APP_ID_RE.search(message)
    return m.group(1) if m else None


def _pending_applications():
    apps=list_applications(limit=200)
    pending=[]
    for a in apps:
        status=(a.get("application_status") or "IN_PROGRESS").upper()
        # Fresh applications without a completed preliminary assessment are pending KYC.
        if not a.get("latest_result") or status in {"IN_PROGRESS","PENDING_KYC","NEEDS_MORE_INFORMATION","MANUAL_REVIEW"}:
            docs=get_documents(a["applicant_id"])
            pending.append({"applicant_id":a["applicant_id"],"full_name":a["full_name"],
                            "status":status,"documents_received":len(docs),
                            "created_at":a.get("created_at")})
    return pending


def chat(message: str):
    text=message.strip()
    low=text.lower()
    if not text:
        return {"reply":"Please enter a request so I can help with account opening or KYC verification.","action":"none"}

    if any(k in low for k in ["what can you do","help","capabilities","how can you help"]):
        return {"reply":"I can help with three supported workflows: (1) start a new account-opening application and collect the required details/documents, (2) look up applications pending KYC or verify an existing application ID, and (3) update an existing applicant's name/address or replace a document. I can also answer questions grounded in the uploaded KYC guideline documents. I cannot approve an account or verify document authenticity independently.","action":"none"}

    if any(k in low for k in ["pending kyc","ids pending","pending applications","applications pending","awaiting kyc","kyc pending"]):
        items=_pending_applications()
        if not items:
            return {"reply":"There are currently no applications pending KYC verification in the application database.","action":"show_pending","applications":[]}
        lines=[f"• {x['applicant_id']} — {x['full_name']} — {x['status']} — {x['documents_received']} document(s)" for x in items]
        return {"reply":"I found these applications requiring KYC attention:\n"+"\n".join(lines),"action":"show_pending","applications":items}

    if any(k in low for k in ["open an account","open account","new account","start an application","apply for an account","fresh application"]):
        guidance=search_knowledge("new customer account opening prerequisites required identity document proof of address information")
        if guidance:
            snippets="\n\n".join(f"[{x['source']}] {x['text']}" for x in guidance[:3])
            reply="Let's start a new account-opening application. Please provide the applicant's full name, contact email, residential address, one accepted identity document (for example passport, driving licence or national ID) and proof of address if required by the applicable guideline. Upload the documents in the form that will open beside this chat.\n\nRelevant indexed guidance:\n"+snippets
        else:
            reply="Let's start a new account-opening application. For this training demo, prepare the applicant's full name, contact email, residential address, an identity document (passport, driving licence or national ID) and proof of address. The actual required documents must be confirmed against your bank-approved guidelines. Upload synthetic/sample documents only."
        return {"reply":reply,"action":"open_new_application"}

    applicant_id=_extract_id(text)
    if applicant_id and any(k in low for k in ["verify","run kyc","process kyc","check kyc","perform kyc"]):
        app=get_application(applicant_id)
        if not app:
            return {"reply":f"I couldn't find application {applicant_id}. Please check the ID or create the application first.","action":"none"}
        docs=get_documents(applicant_id)
        if not docs:
            return {"reply":f"Application {applicant_id} exists, but no documents have been submitted. Upload the required identity and address documents before running KYC verification.","action":"upload_document","application_id":applicant_id}
        try:
            result=process_application(applicant_id,ProcessRequest())
            return {"reply":f"KYC checks completed for {applicant_id}. Preliminary workflow status: {result['workflow_status']}. Preliminary risk: {result['preliminary_assessment']['preliminary_risk_band']}. Verification issues: {', '.join(x['code'] for x in result.get('verification_issues', [])) or 'None'}. Human review required for this case: {result['human_review_required']}. This is not final account approval.","action":"show_application","application_id":applicant_id,"result":result}
        except Exception as exc:
            return {"reply":f"I couldn't complete KYC processing for {applicant_id}: {type(exc).__name__}. Please inspect the application and audit events.","action":"show_application","application_id":applicant_id}

    if applicant_id and any(k in low for k in ["status","details","show application","application details","document status"]):
        app=get_application(applicant_id)
        if not app:
            return {"reply":f"Application {applicant_id} was not found.","action":"none"}
        docs=get_documents(applicant_id)
        status=app.get("application_status") or "IN_PROGRESS"
        return {"reply":f"Application {applicant_id} belongs to {app['full_name']}. Current status: {status}. Documents received: {len(docs)}. Use the application panel to inspect document inventory and audit history.","action":"show_application","application_id":applicant_id,"application":app}

    if applicant_id and any(k in low for k in ["change name","update name","modify name","rename"]):
        m=re.search(r"(?:change|update|modify)\s+(?:the\s+)?name\s+(?:to|as)\s+(.+)$",text,re.I)
        if m:
            new_name=re.sub(r"\s+(?:for|on)\s+(?:application|app)\s*(?:id\s*)?(?:[:#-]\s*)?[A-Za-z0-9_-]+$", "", m.group(1), flags=re.I).strip().strip(' .')
        else:
            new_name=""
        if not m or not new_name:
            return {"reply":f"I can update the name for {applicant_id}. Please phrase it as: 'Change name to [new full name] for application {applicant_id}'.","action":"none"}
        if len(new_name)<2 or len(new_name)>120:
            return {"reply":"Please provide a valid full name (2–120 characters).","action":"none"}
        if not get_application(applicant_id):
            return {"reply":f"Application {applicant_id} was not found.","action":"none"}
        update_application(applicant_id,full_name=new_name)
        add_event(applicant_id,"APPLICATION_NAME_UPDATED",{"new_full_name":new_name,"source":"copilot_chat"})
        docs=[d for d in get_documents(applicant_id) if d["status"]!="SUPERSEDED"]
        if docs:
            result=process_application(applicant_id,ProcessRequest())
            return {"reply":f"Updated the applicant name for {applicant_id} and automatically re-ran KYC. Result: {result['workflow_status']}. Issues: {', '.join(x['code'] for x in result.get('verification_issues', [])) or 'None'}.","action":"show_application","application_id":applicant_id,"result":result}
        return {"reply":f"Updated the applicant name for {applicant_id}. No active documents are available yet, so KYC will run automatically after document submission.","action":"show_application","application_id":applicant_id}

    if applicant_id and (any(k in low for k in ["change document","replace document","update document","upload new document","document change","replace passport","change passport","update passport","replace driving licence","replace national id","replace proof of address"]) or re.search(r"(?:replace|change|update)\s+(?:the\s+)?(?:passport|driving\s+licence|national\s+id|proof\s+of\s+address)", low)):
        if not get_application(applicant_id):
            return {"reply":f"Application {applicant_id} was not found.","action":"none"}
        return {"reply":f"Please select the replacement document type and upload the new file for {applicant_id}. The previous document and replacement event will remain auditable.","action":"upload_document","application_id":applicant_id}

    if applicant_id and any(k in low for k in ["update address","change address","modify address"]):
        m=re.search(r"(?:update|change|modify)\s+(?:the\s+)?address\s+(?:to|as)\s+(.+)$",text,re.I)
        if not m:
            return {"reply":f"Please provide the new address using: 'Update address to [new address] for application {applicant_id}'.","action":"none"}
        address=m.group(1).strip()
        if not get_application(applicant_id):return {"reply":f"Application {applicant_id} was not found.","action":"none"}
        update_application(applicant_id,application_address=address)
        add_event(applicant_id,"APPLICATION_ADDRESS_UPDATED",{"new_address":address,"source":"copilot_chat"})
        docs=[d for d in get_documents(applicant_id) if d["status"]!="SUPERSEDED"]
        if docs:
            result=process_application(applicant_id,ProcessRequest())
            return {"reply":f"Updated the address for {applicant_id} and automatically re-ran KYC. Result: {result['workflow_status']}. Issues: {', '.join(x['code'] for x in result.get('verification_issues', [])) or 'None'}.","action":"show_application","application_id":applicant_id,"result":result}
        return {"reply":f"Updated the application address for {applicant_id}. No active documents are available yet; KYC will run automatically after document submission.","action":"show_application","application_id":applicant_id}

    # Policy questions are answered only when retrieval has relevant indexed guidance.
    policy_terms=["kyc","document","passport","proof of address","address verification","identity","expiry","expired","verification","risk","onboarding","account opening","guideline","guidelines","requirements","escalation"]
    if any(term in low for term in policy_terms):
        hits=search_knowledge(text,n_results=4)
        relevant=[h for h in hits if h.get("distance") is not None and h["distance"] <= float(os.getenv("RAG_SCOPE_DISTANCE_THRESHOLD", "0.75"))]
        if not relevant:
            return {"reply":"I couldn't find sufficiently relevant information for this question in the uploaded KYC guideline knowledge base. This may be outside the approved guideline scope, or the guideline documents may not yet be indexed. Please upload the approved guideline or ask an authorised reviewer. I won't invent a policy answer.","action":"out_of_scope"}
        excerpts=[]
        for h in relevant[:3]:
            excerpts.append(f"Source: {h['source']} (chunk {h['chunk_index']})\n{h['text']}")
        return {"reply":"Based on the uploaded KYC guidance, these are the relevant passages. Please treat them as guidance for human review, not an automated final decision:\n\n"+"\n\n---\n\n".join(excerpts),"action":"policy_answer","sources":[{"source":h['source'],"chunk_index":h['chunk_index']} for h in relevant]}

    return {"reply":"I can help with account opening, pending KYC application lookup, existing application updates, KYC verification, and questions answered from uploaded KYC guidelines. This request doesn't match a supported workflow or the indexed guideline scope. Please rephrase or choose one of those tasks.","action":"out_of_scope"}
