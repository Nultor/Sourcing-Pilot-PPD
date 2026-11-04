-- The inputs of fct_volume_at_risk must match the ground truth (all text there). Returns bad rows:
--   shortfall (pieces) = max(demand - baseline capacity, 0) from ground_truth.saturation
--   product forecast   = ground_truth.forecast
--   pieces per product = ground_truth.bom
-- e.g. AC 366413968 in 2029Q4 (snapshot 2026Q4) is short 119,810 pieces.
-- Stretch: staging fills a blank stretch forecast with an estimate, so like
-- assert_stretch_saturation_matches_ground_truth the component allows 0.5% of its stretch
-- demand, and an imputed product stretch forecast isn't compared.

select
    v.snapshot_quarter, v.ac_code, v.pf_code, v.forecast_quarter,
    v.shortfall_baseline, s.qty_baseline as truth_qty_baseline, s.baseline_capacity as truth_capacity,
    v.pf_qty_baseline, f.qty_baseline as truth_pf_qty_baseline,
    v.qty_per_pf, b.qty_per_pf as truth_qty_per_pf
from {{ ref('fct_volume_at_risk') }} v
left join {{ source('ground_truth', 'saturation') }} s
    on  s.snapshot_quarter = v.snapshot_quarter
    and s.ac_code = v.ac_code
    and s.quarter = v.forecast_quarter
left join {{ source('ground_truth', 'forecast') }} f
    on  f.snapshot_quarter = v.snapshot_quarter
    and f.pf_code = v.pf_code
    and f.quarter = v.forecast_quarter
left join {{ source('ground_truth', 'bom') }} b
    on  b.snapshot_quarter = v.snapshot_quarter
    and b.pf_code = v.pf_code
    and b.ac_code = v.ac_code
where s.ac_code is null
   or f.pf_code is null
   or b.pf_code is null
   or v.shortfall_baseline <> greatest(s.qty_baseline::numeric - s.baseline_capacity::numeric, 0)
   or abs(v.shortfall_stretch - greatest(s.qty_stretch::numeric - s.baseline_capacity::numeric, 0))
        > 0.005 * s.qty_stretch::numeric
   or v.pf_qty_baseline <> f.qty_baseline::numeric
   or (not v.is_stretch_imputed and v.pf_qty_stretch <> f.qty_stretch::numeric)
   or v.qty_per_pf <> b.qty_per_pf::numeric
