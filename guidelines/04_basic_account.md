# Basic Account — training summary

## Public product context
Lloyds' published personal banking terms describe its Basic Account as intended for customers who are legally resident in the UK and do not qualify for one of its other bank accounts. Product terms and eligibility can change; confirm the current terms and application journey.

## Demo intake checklist
- Applicant's identity and date of birth
- UK residential/legal residence information
- Current address and supporting evidence as required
- Contact details
- Employment/income/funding information requested by the application journey
- Reason the applicant is being considered for a Basic Account (capture as applicant-provided information; do not make an automated adverse decision)

## Demo verification rules
- Perform the same identity and address consistency checks as the general personal account workflow.
- Missing evidence => `NEEDS_MORE_INFORMATION`.
- Conflicting or ambiguous identity/address => `MANUAL_REVIEW`.
- Do not decide that a person does or does not qualify for a Basic Account solely from a demo questionnaire.

No credit, fraud, AML, sanctions or official residency checks are performed by this sample workflow.
