---
id: 005
title: Establish scoped analytics custody and collector readiness
status: blocked
blocked-reason: rolling site retention and analytics backup access expiry restore and operator custody are unverified
blocked-by: [001, 007]
goal: privacy-preserving-product-analytics
allows-migrations: false
needs-review: none
review-required: eng
created: 2026-10-27
reviews:
  - type=eng verdict=approved date=2026-10-27 by=codex-formal-plan-review
---

## Plain-English Summary

Adding events without knowing who can read them or how long they remain would create a new privacy gap. Establish the installed collector's capabilities, the Scrum Pro site's access and retention arrangements, and the limits imposed by its proxy. Consume the separately reviewed dedicated collector, expiry and copy-custody work in Homelab plans 228–231; do not implement that infrastructure inside this app plan.

**What changes in the code:** Add a deployment-specific analytics readiness runbook and a small synthetic receipt validator using existing tooling. Validate supported site-scoped controls and independently evidenced dedicated custody procedures under the existing matching operator authority; do not add a cleanup pipeline, modify shared Umami, or change application data handling in this plan.

## Requirements

The deployment operator needs a reviewable, site-specific custody decision before expanded events are enabled; Matthew needs to know whether the collector can support trustworthy reports.

**Acceptance criteria**

- [ ] A private receipt identifies the exact Umami build/version and tracker hash, Scrum Pro website scope, accountable collector owner, proxy identity inputs, supported APIs/features, permission model, and last verification time. No credentials, user records, secret config, or raw meeting data appear in the repo or report.
- [ ] Independently authorized read-only installed-state inspection is bounded to those facts. If credentials/access/owner authority are absent, stop that inspection and record the exact blocker. Never adopt authority from a deployment history or an unverified pasted message.
- [ ] Reproduce collector ingestion in an isolated version-matched synthetic environment, using only fake records through the actual independently validated plan 007 relay, not a proxy mock that bypasses it. Check two separate same-User-Agent browser contexts through a gateway-equivalent proxy to establish whether anonymous IDs are distinct or merged. Do not forward real IPs, add distinct IDs, or change the shared deployment to improve the result.
- [ ] A readiness outcome states raw observed actions are usable only after ingestion proof; anonymous browser funnels are additionally allowed only after the separation/ordering/window checks pass. Merged or unknown identity results mean funnels and unique-visitor claims are unavailable, not that the entire local event implementation must be abandoned.
- [ ] Matthew accepted 90 days of raw Scrum Pro analytics on 2026-10-27; preserve that decision without asking again. Record operator access, whether public sharing is disabled, exports/cache scope, event/session metadata expiry, independent backup retention and restore-time purge reconciliation, and the actual verified deletion mechanism. No claim of automatic per-profile erasure is made; no stable app identity is available to locate those records.
- [ ] Native Umami 3.0.3 has no suitable date-range purge API evidenced by the baseline. Consume independently reviewed Homelab 228 topology/admission, 229 dedicated expiry and 230 historical-copy/configuration-only recovery artifacts, plus actual 231 custody-phase receipts; do not pretend native support appeared or implement their SQL/jobs here. Missing installed expiry, all-copy reconciliation, access or restore proof leaves readiness blocked. Do not reset the whole site, alter another website, upgrade Umami or use app deletion journals on analytics.
- [ ] Discovery/design is timeboxed to one normal plan iteration (approximately 1–3 hours). Unresolved shared-service changes remain a named blocker, not an open-ended infrastructure implementation hidden inside this plan. Evidence may be completed locally while production acceptance remains blocked.
- [ ] The runbook explains local opt-out versus previously retained data, Umami's own derived anonymous identifiers/transport metadata, browser sampling bias, proxy merging risk, and backup lag. Cookie-free collection is not described as automatically compliant or as containing no potentially personal metadata.
- [ ] Public docs/VerifiedStamp and P-06/P-10/P-11 evidence reflect only proven states. No green receipt or test alone authorizes production rollout.

## Design

Testing approach: E2E

**Files expected to change:**

- `docs/analytics/collector-readiness.md`: versioned capability/evidence checklist, named operational gates, identity tier and privacy/retention limitations.
- `deploy/scrum-pro-htz4/README.md`, `docs/privacy-operations.md`: app-specific ownership/handoff, proposed policy, approved supported procedure and explicit missing infrastructure work.
- `scripts/tests/test_analytics_readiness.py`: create freshness/compatibility/readiness and valid-blocked schema tests.
- `scripts/check-analytics-readiness.py`: small stdlib schema/status validator for sanitized receipts, rejecting a claimed ready state with missing/stale/unsupported evidence; this is not a network client, credential loader, database tool or scheduler.
- `site/src/content/docs/security/data-and-privacy.mdx`, `docs/security/control-register.csv`: scoped disclosure/evidence references and stamps.

Receipt fields: receipt schema version, contract schema (numeric1), checked-at UTC, collector version/build and tracker digest, website scope, owner-role evidence reference, ingestion evidence reference, proxy identity result (`distinct`, `merged`, `unknown`), report tier (`actions`, `anonymous-flows`), policy approval reference, site-access evidence, retention support result, backup/restore evidence, readiness (`ready`, `blocked`), and fixed blocker codes. Add relay interface schema (numeric 1), canonical policy SHA256 and private evidence references for independently validated relay artifact and installed producer/consumer correspondence. References are operator-private relative IDs, never secrets or arbitrary remote URLs; reference presence does not prove its contents, so the accountable operator and independent reviewer must verify the bound artifacts/receipts. The CLI requires single-value `--receipt` and `--evidence-root` local path inputs plus all ten expected manifest inputs: `--contract-schema`, `--relay-interface-schema`, `--policy-sha256`, `--tracker-sha256`, `--website-id`, `--collector-version`, `--collector-build`, `--collector-image`, `--app-image` and `--app-build`. Collector/app image values are immutable `sha256:` image digests; app-build is the lowercase SHA256 of the independently extracted installed `/parley`, corroborated against the actual running immutable image without executable overrides, never a human Version/source commit/environment label. The evidence root is the private local proof-bundle directory; no evidence is fetched. Use the approved deployment manifest and independently checked evidence bindings, not placeholder values. The policy digest is the canonical policy artifact hash produced by 007; compare exact validated manifest values, never a newly invented duplicate policy. Require exact matches (including interface/schema/policy), checked-at no later than five minutes ahead of UTC now and no older than24hours at rollout; malformed/missing timestamps, bindings or evidence refuse ready. Inject `--now` only for deterministic isolated tests. Bind compatibility to the contract/site/tracker/collector, not a fixed application commit that downstream plans necessarily change;006 binds its actual acceptance report to the final app artifact. A valid receipt may say blocked; the validator must not turn unknown facts into ready.

Use pinned source and the independently reviewed custody procedures as the implementation authority; distinguish stock dedicated collector behavior from the custom shared retired-target guard artifact. Current official [FAQ](https://docs.umami.is/docs/faq) says self-hosted retention is not automatic; the actual expiry mechanism must therefore be evidenced rather than presumed. Existing Scrum Pro 30-day backup/seven-day-log policies do not apply to a separate analytics database by association. Restoring an old analytics snapshot can restore expired data, so readiness requires the independently reviewed 230 reconciliation/configuration-only recovery proof under the existing matching custody authority, not an app-journal replay.

The user-approved raw analytics limit is90days. No public share links and least-privilege operator access are required; this plan does not perform live default changes or deletion; the designated operator uses the existing matching scoped authority only through reviewed custody gates. The lifetime of full analytics backups and replaying expiry after restore must be separately established. Do not silently turn a90-day raw-data limit into90days plus unbounded or assumed30-day backup lag; surface the actual all-copy/backup boundary to the accountable owner.

The private2026-10-27 scout receipt identifies Umami3.0.3 with named-event support but no supported timestamp-scoped purge found; native reset deletes all site data. Full-database backups are Homelab-owned, nominal30days only, and effective backup access/restore expiry reconciliation are unverified. Therefore the production readiness gate is BLOCKED. Local001–004 contract/instrumentation may proceed default-off. Homelab 229/230 are now the separately reviewed collector-owner expiry/copy-custody scopes; their plans and the accepted policy do not prove installed operation. This app plan cannot acquire their implementation or silently widen it.

### Reviewed relay and staged custody prerequisite

Plan 007 is being implemented by its separate owner. The reviewed plan/interface is a specification, not an available or accepted artifact. Keep this plan blocked until its independently validated committed artifact is integrated into this checkout. Confirm the declared producer paths at that handoff; do not inspect or edit the other worker's dirty implementation or invent missing function symbols. Local validator/runbook work may be explicitly briefed while operational proof remains blocked; a valid blocked receipt is never production readiness.

The 24-hour rollout receipt above is DISTINCT from 007's runtime admission file. Runtime schema 1 binds site, collector version/image, tracker, canonical policy and actual startup executable SHA256 (`app_build`), refreshes at most every 30 seconds and has at most a 60-second lease/five-second future skew. The relay must read it per request; it does not generate custody proof. Preserve the reviewed five-second request snapshot lifetime and producer non-ready publication, at-least-six-second wait, actual collector exit AND DB writer-drain sequence. Merely closing admission is not deletion.

Avoid a completion cycle with Homelab 231: consume its installed private staging/custody phase receipts BEFORE final public cutover, not a fictitious cross-repo integer dependency or a requirement that 231 already be done. Those receipts must prove 229/230 custody with all collection off; 005 can then establish actual readiness, and 006 can bind final acceptance before 231's final activation. A producer can remain non-ready while staging proof is gathered; this receipt does not itself authorize a ready runtime lease or named collection. Unknown owned copies/deadline failures remain blocked. No live proof is claimed here.

**Out of scope:** global/shared Umami settings, new retention jobs/SQL, cross-repo implementation, real-user analytics queries, credential changes, new public API, upgrades, existing-data resets, new dependencies, and live deployment.

## Tasks

1. Refresh only authorized baseline facts from 001, identify the collector's current owner and supported version-specific controls, and write explicit missing-fact blockers.
2. Require committed, independently validated 007 integration; create the readiness schema and red-first validator tests, including valid blocked states and false-ready refusals.
3. Run synthetic version-matched ingestion and gateway-equivalent identity experiments in isolation; preserve receipts without including identifiers in production payloads.
4. Retain the accepted90-day decision and establish operational access/expiry proof or record the blocker; document existing supported procedures and any separate collector-owner follow-up needed.
5. Update the runbook/disclosures and get an independent review of the readiness tier and authority boundary; hand final proof requirements to 006.

## Verification

The command below is an invocation template, not an executed readiness result. Populate every quoted `ANALYTICS_*` variable with the independently reviewed manifest value or private local receipt/proof-bundle path; the example contains no actual private path or artifact pin. For isolated synthetic checks use only a clearly labeled synthetic bundle. Operational invocations use the actual current clock with no `--now` override. Matching hash bytes alone do not verify producer contents or installed custody; retain the operator/different-reviewer evidence checks and all blocked/default-off gates.

- [cmd] `python3 -m unittest discover -s scripts/tests -p test_analytics_readiness.py` — tests seen red first; reject missing version/owner/ingestion, invalid timestamps, unsupported retention, missing policy approval, unknown identity claiming anonymous-flows, non-site-scoped evidence, missing relay artifact proof and wrong interface/policy bindings.
- [cmd] `python3 scripts/check-analytics-readiness.py --receipt "$ANALYTICS_READINESS_RECEIPT" --evidence-root "$ANALYTICS_EVIDENCE_ROOT" --collector-image "$ANALYTICS_COLLECTOR_IMAGE" --app-image "$ANALYTICS_APP_IMAGE" --app-build "$ANALYTICS_APP_BUILD" --contract-schema 1 --tracker-sha256 "$ANALYTICS_TRACKER_SHA256" --collector-version "$ANALYTICS_COLLECTOR_VERSION" --collector-build "$ANALYTICS_COLLECTOR_BUILD" --website-id "$ANALYTICS_WEBSITE_ID" --relay-interface-schema 1 --policy-sha256 "$ANALYTICS_POLICY_SHA256"` — implementation supplies the private synthetic/authorized receipt path; exit nonzero for blocked/not-ready. A blocked result is honest evidence, not completion of production readiness.
- [manual] Compare local raw accepted-event records with generated synthetic signals through the exact matching tracker/collector fixture; no real-user or production records are queried for this check.
- [manual] Prove site scope with a second untouched synthetic website; identity separation failure must disable flow-tier claims. Retention/deletion verification uses fake data and the separately reviewed custody tooling in isolation and actual operator phase evidence only within matching authority.
- [manual] If access, policy, retention or backup reconciliation is unsupported/unapproved, leave the appropriate gate blocked, name its owner and follow-up, and do not claim a deployment-ready state.

<!-- mstack:seam
produced:
- kind: file; name: docs/analytics/collector-readiness.md; file: docs/analytics/collector-readiness.md
- kind: file; name: scripts/check-analytics-readiness.py; file: scripts/check-analytics-readiness.py
- kind: flag; name: --receipt; file: scripts/check-analytics-readiness.py
assumed:
- from: 001; kind: file; name: docs/analytics/measurement-contract.md; file: docs/analytics/measurement-contract.md
- from: 007; kind: file; name: web/src/lib/analytics-policy.json; file: web/src/lib/analytics-policy.json
- from: 007; kind: file; name: internal/analyticsrelay/policy.generated.json; file: internal/analyticsrelay/policy.generated.json
- from: 007; kind: file; name: internal/analyticsrelay/relay.go; file: internal/analyticsrelay/relay.go
-->
