-- Capacity saturation per component (AC) and forecast quarter (README §3.1).
-- Grain: snapshot_quarter x ac_code x forecast_quarter.
--
--   baseline capacity = lines in use today (own plant + current suppliers), without CMs
--   stretch capacity  = baseline capacity + available capacity of CMs qualified for the AC

with forecast as (

    select * from {{ ref('stg_finance_forecast') }}

),

bom as (

    select * from {{ ref('int_bom') }}

),

capacity as (

    select * from {{ ref('int_line_capacity') }}

),

-- PF forecast x quantity per PF, summed per component
demand as (

    select
        f.snapshot_quarter,
        b.ac_code,
        f.forecast_quarter,
        sum(f.qty_baseline * b.qty_per_pf) as qty_baseline,
        sum(f.qty_stretch  * b.qty_per_pf) as qty_stretch
    from forecast f
    join bom b
        on  b.snapshot_quarter = f.snapshot_quarter
        and b.pf_code = f.pf_code
    group by 1, 2, 3

),

baseline_capacity as (

    select
        snapshot_quarter,
        ac_code,
        sum(capacity_per_quarter_checked) as baseline_capacity
    from capacity
    group by 1, 2

),

-- one row per AC x CM, so a CM listed on several lines of the same AC is counted once
qualified_cm as (

    select distinct
        snapshot_quarter,
        ac_code,
        cm,
        cm_available_capacity_per_quarter
    from capacity
    where cm is not null
      and cm_qualified

),

cm_capacity as (

    select
        snapshot_quarter,
        ac_code,
        sum(cm_available_capacity_per_quarter) as qualified_cm_capacity
    from qualified_cm
    group by 1, 2

),

joined as (

    select
        d.snapshot_quarter,
        d.ac_code,
        d.forecast_quarter,
        d.qty_baseline,
        d.qty_stretch,
        bc.baseline_capacity,
        bc.baseline_capacity + coalesce(cm.qualified_cm_capacity, 0) as stretch_capacity
    from demand d
    join baseline_capacity bc
        on  bc.snapshot_quarter = d.snapshot_quarter
        and bc.ac_code = d.ac_code
    left join cm_capacity cm
        on  cm.snapshot_quarter = d.snapshot_quarter
        and cm.ac_code = d.ac_code

)

select
    snapshot_quarter || '|' || ac_code || '|' || forecast_quarter as saturation_key,
    snapshot_quarter,
    ac_code,
    forecast_quarter,
    qty_baseline,
    qty_stretch,
    baseline_capacity,
    stretch_capacity,
    round(qty_baseline / nullif(baseline_capacity, 0), 4) as baseline_saturation,
    round(qty_stretch  / nullif(stretch_capacity, 0), 4)  as stretch_saturation,
    -- cross cases, for the full matrix in the business case
    round(qty_baseline / nullif(stretch_capacity, 0), 4)  as baseline_qty_on_stretch_capacity,
    round(qty_stretch  / nullif(baseline_capacity, 0), 4) as stretch_qty_on_baseline_capacity
from joined
