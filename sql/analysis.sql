-- DuckDB queries. All prices are Australian cents per litre.

-- 1. Coverage per product and month; site IDs describe reporting signatures.
SELECT strftime(month, '%Y-%m') AS source_month, product,
       COUNT(*) AS observations, COUNT(DISTINCT site_id) AS reported_outlets,
       COUNT(DISTINCT observed_date) AS observed_days,
       MIN(observed_date) AS first_date, MAX(observed_date) AS last_date
FROM price_observations
GROUP BY month, product
ORDER BY month, product;

-- 2. Distribution of all observations in a month, not sales-volume-weighted.
SELECT strftime(month, '%Y-%m') AS source_month, product,
       ROUND(median(price_cpl), 2) AS observation_median_cpl,
       ROUND(quantile_cont(price_cpl, 0.25), 2) AS p25_cpl,
       ROUND(quantile_cont(price_cpl, 0.75), 2) AS p75_cpl,
       COUNT(*) AS observations
FROM price_observations
GROUP BY month, product
ORDER BY month, product;

-- 3. Exact consecutive-date movements, pooled over observed pairs.
-- These are descriptions, not a recommended purchasing threshold.
SELECT product, COUNT(*) AS consecutive_pairs,
       COUNT(*) FILTER (WHERE is_large_move) AS large_move_pairs,
       ROUND(100.0 * COUNT(*) FILTER (WHERE is_large_move) / COUNT(*), 2) AS large_move_pct,
       ROUND(median(change_cpl), 2) AS median_change_cpl
FROM matched_site_changes
GROUP BY product
ORDER BY product;

-- 4. Comparison coverage. The earliest loaded date has no previous loaded day.
SELECT c.observed_date, c.product, COUNT(*) AS current_observations,
       COUNT(p.site_id) AS eligible_previous_day_pairs,
       ROUND(100.0 * COUNT(p.site_id) / COUNT(*), 2) AS pair_coverage_pct
FROM price_observations c
LEFT JOIN price_observations p ON c.site_id = p.site_id AND c.product = p.product
    AND p.observed_date = c.observed_date - 1
GROUP BY c.observed_date, c.product
ORDER BY c.observed_date, c.product
LIMIT 21;

-- 5. Partition lineage. Raw files retain earlier bytes after corrections.
SELECT strftime(month, '%Y-%m') AS source_month, revision, row_count,
       min_date, max_date, source_sha256, source_url
FROM source_months
ORDER BY month;

-- 6. Run history: audit attempts are expected to grow on identical replay.
SELECT run_id, as_of, status, loaded_months, skipped_months, loaded_rows, error
FROM pipeline_runs
ORDER BY started_at DESC
LIMIT 10;
