# EPIC-S7-001 — Online disability claim submission for plan sponsors

| | |
|---|---|
| **Id** | EPIC-S7-001 |
| **Type** | Project (S7 — full-scale development & delivery) |
| **Raised by** | Group Benefits Operations, MapleSure Insurance |
| **Target application** | MapleSure SponsorConnect (plan sponsor portal) |
| **Scope** | Multi-sprint, business-driven |
| **Status** | Intake — not yet assessed |

> **Synthetic.** MapleSure Insurance is a fictional insurer. This epic is written
> for the AMS tabletop exercise. It contains no client data, no PII, and no
> client-identifiable information (hard rules 1 and 2).

---

## 1. Business context

MapleSure sells group disability coverage to **plan sponsors** — employer
organizations that sponsor coverage for their employees. The covered employees
are **members**.

When a member goes off work on disability, a claim must reach MapleSure's
intake team. Today that submission is the plan sponsor's problem to solve, and
it happens entirely outside SponsorConnect.

## 2. Current state

The current process is fragmented paper and PDF with limited visibility:

- The member completes an employee statement form. The plan sponsor completes a
  separate employer statement. An attending physician's statement is chased
  separately.
- Forms are gathered by the plan sponsor's HR or benefits administrator over
  email, fax, or post, then sent to MapleSure for manual intake and indexing.
- Attachments arrive detached from the forms they belong to and must be matched
  by hand.
- Member and policy details are re-keyed by the sponsor on every form, and
  re-keyed again by intake. Transcription errors are a known rework driver.
- **The plan sponsor has no way to see whether a submission arrived**, what is
  missing, or where it sits. Status is answered by phone call to the service
  desk.

Operational consequences the business has named: intake rework from incomplete
or mismatched packets, avoidable service-desk contact volume that is purely
status-chasing, and no reliable measure of how long submission actually takes.

## 3. Target state — the business ask

> Give plan sponsors a guided online way to submit a disability claim for a
> member through SponsorConnect, and let them see that it arrived and what is
> still outstanding.

Capabilities requested, at epic level:

1. **Identify the plan and member.** The sponsor identifies whose claim this is
   from the policy number and member id they already hold.
2. **Pre-populate what MapleSure already knows.** Member and plan details held
   against that policy and member id are shown rather than re-keyed. The sponsor
   corrects rather than transcribes.
3. **Collect the disability claim details.** The structured facts of the claim —
   the employment and absence information the intake team needs to open a file.
4. **Support multiple document uploads.** The supporting statements and any
   medical documentation, attached to the submission rather than sent detached.
5. **Confirm receipt.** An immediate, unambiguous confirmation with a reference
   the sponsor can quote.
6. **Expose submission status.** The sponsor can see the state of a submission
   they made, and what is outstanding, without calling the service desk.

## 4. In scope

- The plan sponsor submission journey in SponsorConnect, end to end.
- Retrieval of member/plan details for pre-population.
- Document upload and association to the submission.
- Handoff of the completed submission into the existing intake/indexing path.
- Submission status visible to the submitting sponsor organization.

## 5. Out of scope

- Member-facing (employee) direct submission. Sponsor-mediated only.
- Adjudication, benefit calculation, or payment. This epic delivers a claim to
  intake; it does not decide it.
- Replacing the intake/indexing system itself.
- Migration of historical claims submitted on paper.
- Broker or third-party administrator access.

## 6. Business rules and constraints

- A submission is only permitted against a member the requesting sponsor
  organization actually sponsors. A sponsor must never be able to retrieve or
  submit for a member outside their own organization.
- Pre-populated details are **shown for confirmation, not silently trusted** —
  the sponsor attests before submission.
- A submission must not be lost if the sponsor's session drops mid-journey.
- Every submission carries an audit trail: who submitted, when, and what was
  attached.
- Uploaded documents are subject to the existing file type and size policy.

## 7. Non-functional expectations

- Availability and performance in line with the existing SponsorConnect service
  standard.
- Accessibility to the standard already applied to SponsorConnect.
- No relaxation of existing authentication or authorization controls.
- Retention of submitted documents follows existing records policy.

## 8. Epic-level acceptance

The epic is done when a plan sponsor can, unaided, submit a complete disability
claim for a member they sponsor through SponsorConnect, receive a reference for
it, see its status later, and MapleSure's intake team receives that submission
as a single associated packet rather than loose documents.

## 9. Expected delivery streams

Named here as the business's own rough expectation. **The AI assessment is what
routes this properly** — this section is an input to that step, not its answer.

- Sponsor portal frontend
- API / services layer
- Database
- Document intake and indexing integration
- Policy/member system of record lookup
- Test

The business has flagged that the member/policy lookup touches a system of
record that **is not modifiable by the delivery team on this timeline** — a
field addition there is a manual, externally-owned change with its own lead
time. This is expected to constrain sequencing.

## 10. Open questions — require SME validation

These are genuinely unresolved and must not be invented downstream:

- The exact forms and statements that constitute a complete packet.
- Which attachments are mandatory versus optional at submission time, and
  whether a partial submission may be saved and completed later.
- The authoritative status values and who is allowed to see each one.
- The precise pre-population rules — which fields come from the system of
  record, which are sponsor-entered, and which may be overridden.
- Whether an in-progress submission has a retention or expiry period.

> Anything downstream that depends on these must be labelled as an assumption
> until an SME confirms it.
