# Shadow Runtime Observation Pack

## Scope
Empirical runtime validation only.
No live logic changes, no optimizations, no async queueing, no refactors.

## Current Phase Status
- OLD remains the only live authority.
- NEW runs as shadow observer only.
- Instrumentation and scripts exist, but statistical evidence is not yet conclusive.
- Promotion of NEW is blocked until dataset integrity and statistical gates pass.

## Session Minimum Requirements
- Session duration: >= 60 minutes (recommended 90)
- Shadow flags:
  - SHADOW_MODE_ENABLED=true
  - SHADOW_NEW_ENGINE_ENABLED=true
  - SHADOW_PERSIST_ENABLED=true
  - SHADOW_RUNTIME_METRICS_ENABLED=true
  - SHADOW_AUDIT_MODE=true
  - SHADOW_DEAD_WATCHDOG_ENABLED=true
  - SHADOW_DEAD_WATCHDOG_MINUTES=5
- Optional hard assert (audit-only):
  - SHADOW_AUDIT_ASSERT_ENABLED=true
- Explain payload run:
  - At least one session with SHADOW_EXPLAIN_ENABLED=true
  - At least one session with SHADOW_EXPLAIN_ENABLED=false
- Artifacts to collect per session:
  - bot log file
  - trade_journal DB file path
  - parser output JSON/CSV
  - reconciliation output JSON
  - overhead audit output JSON

## Runtime Checklist
1. Start session with explicit env flags and fixed start timestamp.
2. Confirm logs contain SHADOW-RUNTIME and SHADOW-DATA lines.
3. Confirm logs contain ENTRY_LOCK acquired/released lines.
4. Run parser on log file(s).
5. Run SQL consolidated checks.
6. Run reconciliation script on DB.
7. Run overhead audit script.
8. Fill session record table.
9. Apply GO/NO-GO gates.

### Windows Runtime Start (Reference)
Use the same terminal session to avoid env drift.

```powershell
$env:SHADOW_MODE_ENABLED = "true"
$env:SHADOW_NEW_ENGINE_ENABLED = "true"
$env:SHADOW_PERSIST_ENABLED = "true"
$env:SHADOW_RUNTIME_METRICS_ENABLED = "true"
$env:SHADOW_EXPLAIN_ENABLED = "false"
.\.venv\Scripts\python.exe main.py
```

Preflight evidence (first minutes):
- Startup line `[SHADOW-FLAGS] mode=ON ...`
- Recurrent lines `SHADOW-RUNTIME` and `SHADOW-DATA`
- Recurrent lines `ENTRY_LOCK acquired` and `ENTRY_LOCK released`
- Recurrent lines `SHADOW-COUNTERS` and `SHADOW-LINK`
- Fail-fast line `SHADOW-DEAD` if no persistence after watchdog window

Quick DB checks:

```sql
SELECT COUNT(*) AS shadow_rows FROM shadow_decision_audit;
SELECT COUNT(*) AS cid_null_rows FROM shadow_decision_audit WHERE candidate_id IS NULL;
SELECT COUNT(*) AS linked_outcomes
FROM shadow_decision_audit
WHERE trade_outcome IN ('WIN','LOSS','UNRESOLVED');
```

## Automatic Post-Run Artifacts
When runtime ends, the supervisor exports a session package automatically:

```text
data/exports/session_<SHADOW_SESSION_ID>/
```

Mandatory files:
- `runtime_config_snapshot.json`
- `shadow_runtime_summary.json`
- `shadow_runtime_summary.csv`
- `shadow_reconcile_report.json`
- `shadow_overhead_report.json`
- `session_validation.json`
- `tool_runs.json`

Session validator output is binary:
- `SESSION VALID`
- `SESSION INVALID`

And includes `shadow_integrity_score` in `session_validation.json`.

## Evidence Policy
- If a metric is not observed in logs/DB, mark it as `NO HAY EVIDENCIA SUFICIENTE`.
- A gate cannot pass with missing data.
- Session without `SHADOW-RUNTIME`/`SHADOW-DATA` lines is invalid for statistical progression.

## Mandatory Metrics Per Session
- ENTRY_LOCK wait_ms p95/max
- ENTRY_LOCK held_ms p95/max
- scan_ms avg/p95/max
- eval_ms avg/p95/max
- persist_ms avg/p95/max
- extra_ms (latency per candidate) avg/p95/max
- rows/min avg/p95/max
- explain_chars avg/p95/max (only explain=true session)
- htf_fetch_ratio avg/max
- c5_drift max
- eval_err total
- persist_err total
- cid_missing total
- hash_delta_total and hash_same_total

## Automatic GO/NO-GO Gates
Gate 1: Operational invisibility
- FAIL if ENTRY_LOCK wait_ms p95 increases > 15% vs baseline
- FAIL if scan_ms avg increases > 10% vs baseline
- FAIL if extra_ms avg > 5.0 ms sustained

Gate 2: Data consistency
- FAIL if c5_drift > 0
- FAIL if snapshot_ts null count > 0
- FAIL if invalid context_hash count > 0
- FAIL if eval_err > 0 or persist_err > 0

Gate 3: Outcome linkage
- FAIL if linkage rate < 99% for rows with candidate_id and closed trade age > grace
- FAIL if unresolved NO_TRADE stale rows exceed threshold

Gate 4: Runtime stability
- FAIL if SQLITE busy/lock symptoms detected in logs
- FAIL if DB growth/hour exceeds storage budget

Decision:
- GO only if all gates pass in at least 3 sessions including 1 high-load OTC session.

## Session Record (Acta)
| Field | Value |
|---|---|
| Session ID |  |
| Date |  |
| Start Time |  |
| End Time |  |
| Duration min |  |
| Explain Enabled |  |
| OTC Load Profile |  |
| Log File |  |
| DB File |  |
| Baseline Ref |  |

### Metric Record
| Metric | Value | Baseline | Delta % | Pass/Fail |
|---|---:|---:|---:|---|
| ENTRY_LOCK wait_ms p95 |  |  |  |  |
| ENTRY_LOCK held_ms p95 |  |  |  |  |
| scan_ms avg |  |  |  |  |
| eval_ms avg |  |  |  |  |
| persist_ms avg |  |  |  |  |
| extra_ms avg |  |  |  |  |
| rows/min avg |  |  |  |  |
| explain_chars avg |  |  |  |  |
| htf_fetch_ratio avg |  |  |  |  |
| c5_drift |  |  |  |  |
| eval_err |  |  |  |  |
| persist_err |  |  |  |  |
| cid_missing |  |  |  |  |
| linkage_rate % |  |  |  |  |
| stale_no_trade |  |  |  |  |
| invalid_hash |  |  |  |  |
| null_snapshot_ts |  |  |  |  |

### Findings
- Observed anomalies:
- Candidate paths not covered:
- Outcome linkage caveats:
- Lock/SQLite observations:

### Decision
- GO / NO-GO:
- Rationale:
- Next action:
