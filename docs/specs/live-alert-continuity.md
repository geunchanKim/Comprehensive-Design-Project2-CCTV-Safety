# Live algorithm and alert continuity (#105)

Base: remote develop 93785a6, checked 2026-11-19. Implementation does not imply deployment or completion of the v95 integration replay.

## Live condition

LIVE_ALGORITHM defaults to baseline. Set f-cd to use floor tracking and single-camera fallback for POST /detections, stored results, PPE, alerts, dashboard snapshots and SSE. Invalid algorithms fail startup. Restart the server and use a new session when changing this setting. Existing results are not converted automatically.

Demo: set LIVE_ALGORITHM=f-cd and DASHBOARD_ALGORITHM=f-cd, choose a new DASHBOARD_SESSION_ID, register calibration and dashboard configuration for that condition, and use VITE_ALGORITHM=f-cd on the frontend. The isolated demo Compose derives its dashboard algorithm from LIVE_ALGORITHM; the regular Compose requires both explicitly. Risk analysis still follows ENABLE_RISK_ANALYSIS; it is not enabled automatically.

Health exposes live_algorithm, live_settings, alert_hold_ms and session_alert_timeout_ms.

## Alert lifecycle

- ALERT_HOLD_MS defaults to 1000. A collision warning missing briefly retains its ID and acknowledgment within one second of the last actual risk observation. last_seen_at_ms is not refreshed during the gap. The held level/distance is the last observation, not a fresh safety assessment.
- PPE uses the same grace only when the person disappears entirely. An observed person with wearing or unknown resolves the PPE warning immediately. Source-clock PPE_MAX_AGE_MS=3000 expiration remains unchanged; unknown is never a missing-equipment vote.
- Grace expiration records ended_at_ms as last_seen_at_ms + ALERT_HOLD_MS, whether the next snapshot still lacks the warning or observes it again after the grace period. Explicit resolution and stream resets retain their immediate end time.
- Zone alerts retain immediate resolution. Zone edits and recompute stream resets also end their affected alerts immediately.
- SESSION_ALERT_TIMEOUT_MS defaults to 3000. All active alerts end after three seconds without a successful snapshot publication, using the server clock. Snapshot/alerts reads, SSE polling or the next publication persist this expiration. There is no background timer when no reader or publisher exists; the next access persists the end time at the timeout boundary.
- Timeout increments snapshot seq once for SSE delivery. Unacknowledged danger history remains visible as inactive. Resumed input creates a new occurrence. IDs do not cross session/profile/algorithm or stream boundaries.
- Require 0 <= ALERT_HOLD_MS < SESSION_ALERT_TIMEOUT_MS. No migration is required. The internal missing marker uses the existing JSON details column and is excluded from API responses.

## Position source

snapshot.objects[].position_source is two_camera or single_camera. One current camera_tracks entry means single_camera, even if the track previously had two cameras. Frontend should visually distinguish estimated single-camera positions. This is provenance, not an accuracy guarantee. SSE uses the same snapshot contract.

## Validation and rehearsal

Regression tests cover live f-cd storage/publication and condition isolation, grace boundaries and acknowledgment preservation, recurrence after grace, stale-input expiration and one seq increment, and position provenance. Run backend and edge suites against isolated test databases.

November 24: verify deployed commit and health settings; prepare a fresh v95 session; replay at original recording speed; compare missing bundles and alert intervals with edge pair_drops/algorithm_replay tools; verify stable card IDs and single_camera styling; check no active alert remains three seconds after input ends. Targets are at least 90% fewer missing bundles versus baseline and at most half the warning intervals. Unit/regression success does not establish these measured targets. Grace uses server time, so accelerated replay/recompute is not a valid measurement of warning interval reduction. Recheck together with the edge chair-position improvements before filming on November 25.

## Chair occlusion hold (PR #107 follow-up)

Conditions with C (`floor_tracking`, including demo `f-cd`) retain the last real two-camera chair position for up to 3000ms of capture time, including the boundary, before calculating risks. Baseline does not retain chairs. Health algorithm settings and detection settings expose `chair_hold_ms`; this is a fixed policy without a new environment variable or Compose setting. Risk analysis still defaults to false.

Held matches and snapshot objects use `position_source=held` and `position_observed_at_ms` (last real capture epoch ms). Their camera_tracks, observations and foot_pixels are empty; velocity is not extrapolated. Detection matching_method is held. A current observation takes precedence, and synthetic positions never renew their own lifetime.

The query uses durable real Detection rows scoped to session, calibration profile and algorithm, excluding future observations. No schema migration or process-local cache is needed; rollback and recompute use existing transaction semantics. Synthetic positions are not inserted into Detection or position CSV exports: use response/snapshot recordings to analyze holding. RiskEvent records include risks calculated with held positions.

This does not triangulate chairs from a single camera. A moved chair or a change of both camera track IDs can leave its old position for up to three seconds. Collision alerts can remain another second under PR #106's independent grace. Without new input, snapshots are not recomputed: clients must respect captured_at_ms/stale_after_ms and the stale-input alert expiry.

For November 24 v95 replay at original speed, check held styling, person-chair alert intervals and false positives, duplicate chairs on reacquisition, and old positions after movement. Simulation 84 to 26 is not a measured server result.
