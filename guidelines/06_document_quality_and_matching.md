# Document quality and field-matching rules — demo policy

## Supported evidence types in this pack
- Passport (synthetic text representation)
- UK photo driving licence (synthetic text representation)
- Utility bill / council tax / bank statement (synthetic text representation)
- UCAS course confirmation letter (synthetic)
- Joint applicant identity and address evidence

## Field matching
- Name: normalise whitespace and case; do not silently treat materially different names as equal. Record exact extracted and declared values.
- DOB: compare ISO dates exactly (`YYYY-MM-DD`). DOB mismatch is a high-severity identity discrepancy.
- Document number: extract and record; this demo does not query an issuing authority.
- Expiry: if present, compare to the processing date. Expired evidence must not pass the demo expiry check.
- Address: compare normalised address components. A partial match is not equivalent to verified address; explain missing or conflicting components.
- Student course: record course name, full-time status, duration and UCAS code. Format check is not UCAS verification.
- Joint account: verify each applicant separately.

## Confidence and escalation
- Missing required fields => `NEEDS_MORE_INFORMATION`.
- Conflicting name or DOB => `MANUAL_REVIEW`.
- Expired identity evidence => `MANUAL_REVIEW` or request acceptable replacement, according to configured workflow.
- Low extraction confidence or ambiguous text => `MANUAL_REVIEW`.
- Never fabricate an extracted value.
- Keep original document text, extracted values, field-level comparisons, tool outcomes, timestamps and decision reasons in the audit trail.

## Security
Use synthetic data only. Do not upload genuine customer identity documents to this training environment.
