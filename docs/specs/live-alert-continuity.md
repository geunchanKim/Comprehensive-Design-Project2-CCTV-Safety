# Live algorithm and alert continuity (#105)

Base: remote develop 93785a6, checked 2026-11-19. Implementation does not imply deployment or completion of the v95 integration replay.

## Live condition

LIVE_ALGORITHM defaults to baseline. Set f-cd to use floor tracking and single-camera fallback for POST /detections, stored results, PPE, alerts, dashboard snapshots and SSE. Invalid algorithms fail startup. Restart the server and use a new session when changing this setting. Existing results are not converted automatically.

Demo: set LIVE_ALGORITHM=f-cd and DASHBOARD_ALGORITHM=f-cd, choose a new DASHBOARD_SESSION_ID, register calibration and dashboard configuration for that condition, and use VITE_ALGORITHM=f-cd on the frontend. The isolated demo Compose derives its dashboard algorithm from LIVE_ALGORITHM; the regular Compose requires both explicitly. Risk analysis still follows ENABLE_RISK_ANALYSIS; it is not enabled automatically.

Health exposes live_algorithm, live_settings, alert_hold_ms and session_alert_timeout_ms.

## Alert lifecycle

- ALERT_HOLD_MS defaults to 1000. A collision warning missing briefly retains its ID and acknowledgment within one second of the last actual risk observation. last_seen_at_ms is not refreshed during the gap. The held level/distance is the last observation, not a fresh safety assessment.
- PPE uses the same grace only when the person disappears entirely. An observed person with wearing or unknown resolves the PPE warning immediately. Source-clock PPE_MAX_AGE_MS=3000 expiration remains unchanged; unknown is never a missing-equipment vote.
- Zone alerts retain immediate resolution. Zone edits and recompute stream resets also end their affected alerts immediately.
- SESSION_ALERT_TIMEOUT_MS defaults to 3000. All active alerts end after three seconds without a successful snapshot publication, using the server clock. Snapshot/alerts reads, SSE polling or the next publication persist this expiration. There is no background timer when no reader or publisher exists; the next access persists the end time at the timeout boundary.
- Timeout increments snapshot seq once for SSE delivery. Unacknowledged danger history remains visible as inactive. Resumed input creates a new occurrence. IDs do not cross session/profile/algorithm or stream boundaries.
- Require 0 <= ALERT_HOLD_MS < SESSION_ALERT_TIMEOUT_MS. No migration is required. The internal missing marker uses the existing JSON details column and is excluded from API responses.

## Position source

snapshot.objects[].position_source is two_camera or single_camera. One current camera_tracks entry means single_camera, even if the track previously had two cameras. Frontend should visually distinguish estimated single-camera positions. This is provenance, not an accuracy guarantee. SSE uses the same snapshot contract.

## Validation and rehearsal

Regression tests cover live f-cd storage/publication and condition isolation, grace boundaries and acknowledgment preservation, recurrence after grace, stale-input expiration and one seq increment, and position provenance. Run backend and edge suites against isolated test databases.

November 24: verify deployed commit and health settings; prepare a fresh v95 session; replay at original recording speed; compare missing bundles and alert intervals with edge pair_drops/algorithm_replay tools; verify stable card IDs and single_camera styling; check no active alert remains three seconds after input ends. Targets are at least 90% fewer missing bundles versus baseline and at most half the warning intervals. Unit/regression success does not establish these measured targets. Grace uses server time, so accelerated replay/recompute is not a valid measurement of warning interval reduction. Recheck together with the edge chair-position improvements before filming on November 25.
