# Onboarding Copilot — behaviour and scope contract

## Supported user intents
1. Start a new retail account-opening application. Explain demo prerequisites and open the intake form.
2. List application IDs pending KYC by querying the application database.
3. Retrieve an application by ID and report its current workflow/document status.
4. Run preliminary KYC processing for an existing application ID.
5. Update applicant name or address, with an audit event and automatic re-verification whenever active documents exist.
6. Replace a document by uploading a replacement against an existing application ID. The old version is marked `SUPERSEDED`; the replacement is processed as the current document.
7. Answer KYC policy questions only from relevant uploaded guideline chunks in ChromaDB. Include source names.

## Out-of-scope behaviour
- For unrelated topics, unsupported banking products, unindexed policies or questions with no sufficiently relevant retrieval result, state that the request is outside the available guideline scope. Do not invent bank policy.
- Do not claim that a document is genuine or that identity is legally verified.
- Do not approve/reject a bank account or make a final AML, sanctions, PEP or fraud decision.
- Do not infer missing or ambiguous document fields.

## Human review and audit
A clean automated pre-check can complete without a human intervention in this demo. Mismatches, missing evidence and expired/ambiguous documents are routed to human review. Final bank account approval remains outside scope. Application creation, document receipt/replacement, field updates, verification checks, document requests, blocked duplicate requests and preliminary outcomes are recorded in the demo audit log.

## Synthetic-data restriction
Use synthetic documents and applicant data only. The training app has no authentication/RBAC and is not suitable for production data.


## Automated preliminary KYC decision
On processing, the orchestrator calls `extract_document_fields` for every active document, compares identity name and DOB with the applicant record, calls `verify_address`, and calls `assign_risk_rating`. The response contains each tool result, field-level matches, mismatch reason codes, document statuses, and a preliminary decision. `PRELIMINARY_KYC_PASSED` means the configured synthetic-data pre-checks passed; it is not a final bank approval. Missing evidence routes to `NEEDS_MORE_INFORMATION`; mismatches/expired evidence route to `MANUAL_REVIEW`. Applicant detail changes and replacement uploads invalidate the prior result and must be reprocessed.
