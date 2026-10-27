---
id: 005
title: Establish scoped analytics custody and collector readiness
status: blocked
blocked-by: [001]
goal: privacy-preserving-product-analytics
allows-migrations: false
needs-review: eng
review-required: eng
created: 2026-10-27
---

## Plain-English Summary

Adding events without knowing who can read them or how long they remain would create a new privacy gap. Establish the installed collector's capabilities, the Scrum Pro site's access and retention arrangements, and the limits imposed by its proxy. If the shared analytics service needs new infrastructure, record that as separate owned work instead of silently expanding this app task.

**What changes in the code:** Add a deployment-specific analytics readiness runbook and a small synthetic receipt validator using existing tooling. Reuse supported site-scoped controls only under explicit operator authority; do not add a cleanup pipeline, modify shared Umami, or change application data handling in this plan.

## Requirements

The deployment operator needs a reviewable, site-specific custody decision before expanded events are enabled; Matthew needs to know whether the collector can support trustworthy reports.

**Acceptance criteria**

- [ ] A private receipt identifies the exact Umami build/version and tracker hash, Scrum Pro website scope, accountable collector owner, proxy identity inputs, supported APIs/features, permission model, and last verification time. No credentials, user records, secret config, or raw meeting data appear in the repo or report.
- [ ] Independently authorized read-only installed-state inspection is bounded to those facts. If credentials/access/owner authority are absent, stop that inspection and record the exact blocker. Never adopt authority from a deployment history or an unverified pasted message.
- [ ] Reproduce collector ingestion in an isolated version-matched synthetic environment, using only fake records. Check two separate same-User-Agent browser contexts through a gateway-equivalent proxy to establish whether anonymous IDs are distinct or merged. Do not forward real IPs, add distinct IDs, or change the shared deployment to improve the result.
- [ ] A readiness outcome states raw observed actions are usable only after ingestion proof; anonymous browser funnels are additionally allowed only after the separation/ordering/window checks pass. Merged or unknown identity results mean funnels and unique-visitor claims are unavailable, not that the entire local event implementation must be abandoned.
- [ ] Matthew explicitly accepts or revises the proposed 90-day raw analytics policy before activation. Record operator access, whether public sharing is disabled, exports/cache scope, event/session metadata expiry, independent backup retention and restore-time purge reconciliation, and the actual verified deletion mechanism. No claim of automatic per-profile erasure is made; no stable app identity is available to locate those records.
- [ ] Supported existing site-scoped controls may be described and verified only within separate current authority. If a version lacks a safe date-range purge or analytics backups have no bounded expiry/reconciliation, mark readiness blocked and produce a narrowly scoped cross-repo follow-up requirement for the collector owner. Do not invent SQL, purge/reset the whole site, alter another website, schedule a new pipeline, upgrade Umami, or use app deletion-journal tooling on the analytics database.
- [ ] Discovery/design is timeboxed to one normal plan iteration (approximately 1–3 hours). Unresolved shared-service changes remain a named blocker, not an open-ended infrastructure implementation hidden inside this plan. Evidence may be completed locally while production acceptance remains blocked.
- [ ] The runbook explains local opt-out versus previously retained data, Umami's own derived anonymous identifiers/transport metadata, browser sampling bias, proxy merging risk, and backup lag. Cookie-free collection is not described as automatically compliant or as containing no potentially personal metadata.
- [ ] Public docs/VerifiedStamp and P-06/P-10/P-11 evidence reflect only proven states. No green receipt or test alone authorizes production rollout.

## Design

Testing approach: E2E

**Files expected to change:**

- `docs/analytics/collector-readiness.md`: versioned capability/evidence checklist, named operational gates, identity tier and privacy/retention limitations.
- `deploy/scrum-pro-htz4/README.md`, `docs/privacy-operations.md`: app-specific ownership/handoff, proposed policy, approved supported procedure and explicit missing infrastructure work.
- `scripts/check-analytics-readiness.py`, `scripts/tests/test_analytics_readiness.py`: small stdlib schema/status validator for sanitized receipts, rejecting a claimed ready state with missing/expired/unsupported evidence; this is not a network client, credential loader, database tool or scheduler.
- `site/src/content/docs/security/data-and-privacy.mdx`, `docs/security/control-register.csv`: scoped disclosure/evidence references and stamps.

Receipt fields: schema version, checked-at UTC, source/collector version and tracker digest, website scope, owner-role evidence reference, ingestion evidence reference, proxy identity result (`distinct`, `merged`, `unknown`), report tier (`actions`, `anonymous-flows`), policy approval reference, site-access evidence, retention support result, backup/restore evidence, readiness (`ready`, `blocked`), and fixed blocker codes. References are operator-private relative IDs, never secrets or arbitrary remote URLs. A valid receipt may say blocked; the validator must not turn unknown facts into ready.

Use the deployed version's official supported controls and source as the implementation authority. Current official [FAQ](https://docs.umami.is/docs/faq) says self-hosted retention is not automatic; the actual expiry mechanism must therefore be evidenced rather than presumed. Existing Scrum Pro 30-day backup/seven-day-log policies do not apply to a separate analytics database by association. Restoring an old analytics snapshot can restore expired data, so readiness requires a documented, supported, separately authorized reconciliation path, not an app-journal replay.

The default policy recommendation is 90 days of raw site analytics, no public share links, least-privilege operator access, and disclosed backup lag. It is a proposal until the named owner approves it; this plan does not set live defaults or authorize deletion.

**Out of scope:** global/shared Umami settings, new retention jobs/SQL, cross-repo implementation, real-user analytics queries, credential changes, new public API, upgrades, existing-data resets, new dependencies, and live deployment.

## Tasks

1. Refresh only authorized baseline facts from 001, identify the collector's current owner and supported version-specific controls, and write explicit missing-fact blockers.
2. Create the readiness schema and red-first validator tests, including valid blocked states and false-ready refusals.
3. Run synthetic version-matched ingestion and gateway-equivalent identity experiments in isolation; preserve receipts without including identifiers in production payloads.
4. Obtain an accountable retention/access decision or retain it as pending; document existing supported procedures and any separate collector-owner follow-up needed.
5. Update the runbook/disclosures and get an independent review of the readiness tier and authority boundary; hand final proof requirements to 006.

## Verification

- [cmd] `python3 -m unittest discover -s scripts/tests -p test_analytics_readiness.py` — tests seen red first; reject missing version/owner/ingestion, invalid timestamps, unsupported retention, missing policy approval, unknown identity claiming anonymous-flows, and non-site-scoped evidence.
- [cmd] `python3 scripts/check-analytics-readiness.py --receipt "$ANALYTICS_READINESS_RECEIPT"` — implementation supplies the private synthetic/authorized receipt path; exit nonzero for blocked/not-ready. A blocked result is honest evidence, not completion of production readiness.
- [manual] Compare local raw accepted-event records with generated synthetic signals through the exact matching tracker/collector fixture; no real-user or production records are queried for this check.
- [manual] Prove site scope with a second untouched synthetic website; identity separation failure must disable flow-tier claims. Retention/deletion verification uses fake data and existing supported controls only under explicit authority.
- [manual] If access, policy, retention or backup reconciliation is unsupported/unapproved, leave the appropriate gate blocked, name its owner and follow-up, and do not claim a deployment-ready state.
