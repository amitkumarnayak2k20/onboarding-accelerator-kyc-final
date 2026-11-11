# Student Current Account — training summary

## Public eligibility points
Lloyds' public Student Current Account page states applicants need to:
- Be aged 17 or over.
- Have been a UK resident for at least 3 years.
- Study full-time on a course lasting at least 2 years, or a one-year access course leading to a degree.
- Have a four-digit UCAS code confirming their course place.

The public page says international students who have not been UK residents for at least 3 years cannot apply for this Student Current Account, but may be able to apply for another Lloyds account. Confirm current rules on the live page.

## Publicly listed evidence examples
- Proof of identity: birth certificate, passport or driving licence.
- Proof of address: driving licence, utility bill or bank statement; a GP, hospital or school letter may also be used.
- Four-digit UCAS code confirming the course place.

## Demo intake checklist
- Applicant details and identity evidence
- Current address and address evidence
- UK residency duration
- Course name, institution, study mode and course duration
- UCAS code (synthetic in this pack)

## Demo verification rules
- Check age is at least 17 on application date.
- Check residency-duration field is at least 3 years.
- Check full-time status and stated course duration against the public criteria above.
- Check a UCAS code is present (format check only; no UCAS lookup).
- Run identity and address matching.
- If a criterion is missing or unclear, return `NEEDS_MORE_INFORMATION`; if conflicting, return `MANUAL_REVIEW`.

The demo cannot validate UCAS enrolment or immigration/residency status against official records.
