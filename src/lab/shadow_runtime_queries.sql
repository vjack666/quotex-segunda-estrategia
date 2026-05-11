-- Shadow runtime consolidated SQL checks
-- Usage (sqlite3):
--   sqlite3 data/db/trade_journal-YYYY-MM-DD.db ".read src/lab/shadow_runtime_queries.sql"

-- 1) Dataset presence
SELECT 'shadow_total_rows' AS metric, COUNT(*) AS value
FROM shadow_decision_audit;

-- 2) Null snapshot timestamp
SELECT 'null_snapshot_ts' AS metric, COUNT(*) AS value
FROM shadow_decision_audit
WHERE context_snapshot_ts IS NULL OR TRIM(context_snapshot_ts) = '';

-- 3) Null/empty hash
SELECT 'empty_context_hash' AS metric, COUNT(*) AS value
FROM shadow_decision_audit
WHERE context_hash IS NULL OR TRIM(context_hash) = '';

-- 4) Candidate linkage basic
SELECT 'candidate_id_null' AS metric, COUNT(*) AS value
FROM shadow_decision_audit
WHERE candidate_id IS NULL;

-- 5) Candidate id not found in candidates
SELECT 'candidate_id_not_found' AS metric, COUNT(*) AS value
FROM shadow_decision_audit s
LEFT JOIN candidates c ON c.id = s.candidate_id
WHERE s.candidate_id IS NOT NULL AND c.id IS NULL;

-- 6) Outcome linkage for rows with candidate_id
SELECT
  'outcome_linkage' AS metric,
  SUM(CASE WHEN candidate_id IS NOT NULL THEN 1 ELSE 0 END) AS with_candidate,
  SUM(CASE WHEN candidate_id IS NOT NULL AND trade_outcome <> 'NO_TRADE' THEN 1 ELSE 0 END) AS linked,
  ROUND(
    100.0 * SUM(CASE WHEN candidate_id IS NOT NULL AND trade_outcome <> 'NO_TRADE' THEN 1 ELSE 0 END)
    / NULLIF(SUM(CASE WHEN candidate_id IS NOT NULL THEN 1 ELSE 0 END), 0),
    2
  ) AS linkage_pct
FROM shadow_decision_audit;

-- 7) Stale NO_TRADE rows (older than 20 minutes)
SELECT 'stale_no_trade_20m' AS metric, COUNT(*) AS value
FROM shadow_decision_audit
WHERE trade_outcome = 'NO_TRADE'
  AND created_at <= datetime('now', '-20 minutes');

-- 8) Compare status distribution
SELECT 'compare_status' AS metric, compare_status AS key, COUNT(*) AS value
FROM shadow_decision_audit
GROUP BY compare_status
ORDER BY value DESC;

-- 9) OLD vs NEW divergence families
SELECT
  'divergence_counts' AS metric,
  SUM(CASE WHEN compare_status = 'OLD_ACCEPT_NEW_REJECT' THEN 1 ELSE 0 END) AS old_accept_new_reject,
  SUM(CASE WHEN compare_status = 'OLD_REJECT_NEW_ACCEPT' THEN 1 ELSE 0 END) AS old_reject_new_accept,
  SUM(CASE WHEN compare_status = 'BOTH_REJECT_DIFF_REASON' THEN 1 ELSE 0 END) AS both_reject_diff_reason,
  SUM(CASE WHEN compare_status = 'AGREE_ACCEPT' THEN 1 ELSE 0 END) AS agree_accept,
  SUM(CASE WHEN compare_status = 'AGREE_REJECT' THEN 1 ELSE 0 END) AS agree_reject,
  SUM(CASE WHEN compare_status = 'NEW_ERROR' THEN 1 ELSE 0 END) AS new_error
FROM shadow_decision_audit;

-- 10) Repeated candidate_id in shadow rows (possible multiple-update risk)
SELECT 'candidate_id_repeated' AS metric, candidate_id AS key, COUNT(*) AS value
FROM shadow_decision_audit
WHERE candidate_id IS NOT NULL
GROUP BY candidate_id
HAVING COUNT(*) > 1
ORDER BY value DESC
LIMIT 50;

-- 11) Martin rows without candidate_id
SELECT 'martin_without_candidate_id' AS metric, COUNT(*) AS value
FROM shadow_decision_audit
WHERE LOWER(stage) = 'martin' AND candidate_id IS NULL;

-- 12) Hash cardinality by asset (context variation sanity)
SELECT 'asset_hash_cardinality' AS metric, asset AS key, COUNT(DISTINCT context_hash) AS value
FROM shadow_decision_audit
GROUP BY asset
ORDER BY value DESC;

-- 13) Rows/min over last 60 minutes
SELECT
  'rows_per_min_last_60m' AS metric,
  ROUND(COUNT(*) / 60.0, 4) AS value
FROM shadow_decision_audit
WHERE created_at >= datetime('now', '-60 minutes');

-- 14) DB size proxy by rows
SELECT 'avg_explain_chars' AS metric, ROUND(AVG(LENGTH(COALESCE(new_explain, ''))), 2) AS value
FROM shadow_decision_audit;

-- 15) WR / PF / Expectancy global (shadow-linked outcomes only)
SELECT
  'wr_pf_expectancy_global' AS metric,
  SUM(CASE WHEN trade_outcome = 'WIN' THEN 1 ELSE 0 END) AS wins,
  SUM(CASE WHEN trade_outcome = 'LOSS' THEN 1 ELSE 0 END) AS losses,
  ROUND(
    100.0 * SUM(CASE WHEN trade_outcome = 'WIN' THEN 1 ELSE 0 END)
    / NULLIF(SUM(CASE WHEN trade_outcome IN ('WIN', 'LOSS') THEN 1 ELSE 0 END), 0),
    2
  ) AS winrate_pct,
  ROUND(
    SUM(CASE WHEN trade_outcome = 'WIN' THEN COALESCE(trade_profit, 0.0) ELSE 0.0 END)
    / NULLIF(ABS(SUM(CASE WHEN trade_outcome = 'LOSS' THEN COALESCE(trade_profit, 0.0) ELSE 0.0 END)), 0),
    4
  ) AS profit_factor,
  ROUND(
    SUM(CASE WHEN trade_outcome IN ('WIN', 'LOSS') THEN COALESCE(trade_profit, 0.0) ELSE 0.0 END)
    / NULLIF(SUM(CASE WHEN trade_outcome IN ('WIN', 'LOSS') THEN 1 ELSE 0 END), 0),
    6
  ) AS expectancy
FROM shadow_decision_audit;

-- 16) WR / PF / Expectancy by NEW category
SELECT
  'wr_pf_expectancy_by_new_category' AS metric,
  new_category AS key,
  SUM(CASE WHEN trade_outcome = 'WIN' THEN 1 ELSE 0 END) AS wins,
  SUM(CASE WHEN trade_outcome = 'LOSS' THEN 1 ELSE 0 END) AS losses,
  ROUND(
    100.0 * SUM(CASE WHEN trade_outcome = 'WIN' THEN 1 ELSE 0 END)
    / NULLIF(SUM(CASE WHEN trade_outcome IN ('WIN', 'LOSS') THEN 1 ELSE 0 END), 0),
    2
  ) AS winrate_pct,
  ROUND(
    SUM(CASE WHEN trade_outcome = 'WIN' THEN COALESCE(trade_profit, 0.0) ELSE 0.0 END)
    / NULLIF(ABS(SUM(CASE WHEN trade_outcome = 'LOSS' THEN COALESCE(trade_profit, 0.0) ELSE 0.0 END)), 0),
    4
  ) AS profit_factor,
  ROUND(
    SUM(CASE WHEN trade_outcome IN ('WIN', 'LOSS') THEN COALESCE(trade_profit, 0.0) ELSE 0.0 END)
    / NULLIF(SUM(CASE WHEN trade_outcome IN ('WIN', 'LOSS') THEN 1 ELSE 0 END), 0),
    6
  ) AS expectancy
FROM shadow_decision_audit
GROUP BY new_category
ORDER BY key;

-- 17) Trades NEW would reject but OLD accepted and lost (NEW potentially saves losses)
SELECT
  'new_saves_old_losses' AS metric,
  COUNT(*) AS value
FROM shadow_decision_audit
WHERE compare_status = 'OLD_ACCEPT_NEW_REJECT'
  AND trade_outcome = 'LOSS';

-- 18) Trades NEW would reject but OLD accepted and won (NEW rejects winners)
SELECT
  'new_rejects_old_winners' AS metric,
  COUNT(*) AS value
FROM shadow_decision_audit
WHERE compare_status = 'OLD_ACCEPT_NEW_REJECT'
  AND trade_outcome = 'WIN';

-- 19) Metrics by asset
SELECT
  'metrics_by_asset' AS metric,
  asset AS key,
  SUM(CASE WHEN trade_outcome = 'WIN' THEN 1 ELSE 0 END) AS wins,
  SUM(CASE WHEN trade_outcome = 'LOSS' THEN 1 ELSE 0 END) AS losses,
  ROUND(
    100.0 * SUM(CASE WHEN trade_outcome = 'WIN' THEN 1 ELSE 0 END)
    / NULLIF(SUM(CASE WHEN trade_outcome IN ('WIN', 'LOSS') THEN 1 ELSE 0 END), 0),
    2
  ) AS winrate_pct
FROM shadow_decision_audit
GROUP BY asset
ORDER BY wins + losses DESC;

-- 20) Metrics by hour
SELECT
  'metrics_by_hour' AS metric,
  strftime('%H', created_at) AS key,
  SUM(CASE WHEN trade_outcome = 'WIN' THEN 1 ELSE 0 END) AS wins,
  SUM(CASE WHEN trade_outcome = 'LOSS' THEN 1 ELSE 0 END) AS losses,
  ROUND(
    100.0 * SUM(CASE WHEN trade_outcome = 'WIN' THEN 1 ELSE 0 END)
    / NULLIF(SUM(CASE WHEN trade_outcome IN ('WIN', 'LOSS') THEN 1 ELSE 0 END), 0),
    2
  ) AS winrate_pct
FROM shadow_decision_audit
GROUP BY strftime('%H', created_at)
ORDER BY key;

-- 21) Metrics by strategy_origin
SELECT
  'metrics_by_strategy_origin' AS metric,
  strategy_origin AS key,
  SUM(CASE WHEN trade_outcome = 'WIN' THEN 1 ELSE 0 END) AS wins,
  SUM(CASE WHEN trade_outcome = 'LOSS' THEN 1 ELSE 0 END) AS losses,
  ROUND(
    100.0 * SUM(CASE WHEN trade_outcome = 'WIN' THEN 1 ELSE 0 END)
    / NULLIF(SUM(CASE WHEN trade_outcome IN ('WIN', 'LOSS') THEN 1 ELSE 0 END), 0),
    2
  ) AS winrate_pct
FROM shadow_decision_audit
GROUP BY strategy_origin
ORDER BY wins + losses DESC;

-- 22) Metrics by veto_count
SELECT
  'metrics_by_veto_count' AS metric,
  CAST(new_veto_count AS TEXT) AS key,
  COUNT(*) AS rows,
  SUM(CASE WHEN trade_outcome = 'WIN' THEN 1 ELSE 0 END) AS wins,
  SUM(CASE WHEN trade_outcome = 'LOSS' THEN 1 ELSE 0 END) AS losses
FROM shadow_decision_audit
GROUP BY new_veto_count
ORDER BY new_veto_count;

-- 23) Metrics by HTF alignment
SELECT
  'metrics_by_htf_alignment' AS metric,
  CASE WHEN new_htf_aligned = 1 THEN 'HTF_ALIGNED' WHEN new_htf_aligned = 0 THEN 'HTF_NOT_ALIGNED' ELSE 'HTF_NULL' END AS key,
  SUM(CASE WHEN trade_outcome = 'WIN' THEN 1 ELSE 0 END) AS wins,
  SUM(CASE WHEN trade_outcome = 'LOSS' THEN 1 ELSE 0 END) AS losses,
  ROUND(
    100.0 * SUM(CASE WHEN trade_outcome = 'WIN' THEN 1 ELSE 0 END)
    / NULLIF(SUM(CASE WHEN trade_outcome IN ('WIN', 'LOSS') THEN 1 ELSE 0 END), 0),
    2
  ) AS winrate_pct
FROM shadow_decision_audit
GROUP BY CASE WHEN new_htf_aligned = 1 THEN 'HTF_ALIGNED' WHEN new_htf_aligned = 0 THEN 'HTF_NOT_ALIGNED' ELSE 'HTF_NULL' END
ORDER BY key;

-- 24) Masaniello impact proxy by cycle_id
SELECT
  'masaniello_cycle_proxy' AS metric,
  CAST(cycle_id AS TEXT) AS key,
  SUM(CASE WHEN trade_outcome = 'WIN' THEN 1 ELSE 0 END) AS wins,
  SUM(CASE WHEN trade_outcome = 'LOSS' THEN 1 ELSE 0 END) AS losses,
  ROUND(SUM(CASE WHEN trade_outcome IN ('WIN', 'LOSS') THEN COALESCE(trade_profit, 0.0) ELSE 0.0 END), 6) AS net_profit
FROM shadow_decision_audit
WHERE cycle_id IS NOT NULL
GROUP BY cycle_id
ORDER BY cycle_id;
