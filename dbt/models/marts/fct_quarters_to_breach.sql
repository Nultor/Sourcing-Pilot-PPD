-- Breach summary per component (AC): when saturation first passes the warning threshold,
-- how often, how badly, and the resulting severity and action (README §3.1).
-- Grain: snapshot_quarter x ac_code. Built on fct_saturation.
--
-- "Over" = saturation above var('warn_threshold') (0.85). Severity, same rule as the data
-- generator (data_gen/saturation.py, classify), checked in this order:
--   none             baseline never over
--   temporary_spike  baseline over in exactly one quarter
--   high             stretch over in 2+ quarters: even all qualified CMs are not enough
--   early_warning    first baseline breach is the 5th forecast quarter or later
--   medium           otherwise: the qualified CMs can absorb the extra demand

with saturation as (

    select
        *,
        row_number() over (
            partition by snapshot_quarter, ac_code
            order by forecast_quarter
        ) as horizon_position          -- 1 = first forecast quarter
    from {{ ref('fct_saturation') }}

),

per_ac as (

    select
        snapshot_quarter,
        ac_code,
        count(*) filter (where baseline_saturation > {{ var('warn_threshold') }}) as n_quarters_baseline_over,
        count(*) filter (where stretch_saturation  > {{ var('warn_threshold') }}) as n_quarters_stretch_over,
        min(forecast_quarter)  filter (where baseline_saturation > {{ var('warn_threshold') }}) as first_breach_quarter,
        min(horizon_position)  filter (where baseline_saturation > {{ var('warn_threshold') }}) as first_breach_position,
        min(forecast_quarter)  filter (where baseline_saturation > {{ var('critical_threshold') }}) as first_critical_quarter,
        max(baseline_saturation)                         as peak_baseline_saturation,
        max(stretch_saturation)                          as peak_stretch_saturation,
        -- pieces per quarter that the lines (+ CMs for stretch) can't make, worst quarter
        round(max(greatest(qty_baseline - baseline_capacity, 0)))::bigint as peak_baseline_shortfall,
        round(max(greatest(qty_stretch  - stretch_capacity, 0)))::bigint  as peak_stretch_shortfall
    from saturation
    group by 1, 2

),

classified as (

    select
        *,
        case
            when n_quarters_baseline_over = 0 then 'none'
            when n_quarters_baseline_over = 1 then 'temporary_spike'
            when n_quarters_stretch_over >= 2 then 'high'
            when first_breach_position >= 5   then 'early_warning'
            else 'medium'
        end as severity
    from per_ac

)

select
    snapshot_quarter || '|' || ac_code as breach_key,
    snapshot_quarter,
    ac_code,
    severity,
    case severity
        when 'none'            then 'no capacity action'
        when 'temporary_spike' then 'no RFQ: manage the one-off peak with stock build or CM'
        when 'high'            then 'RFQ for new capacity or investment (even all qualified CMs are not enough)'
        when 'medium'          then 'activate CM short term, consider RFQ / investment to restore buffer'
        when 'early_warning'   then 'plan RFQ / investment before the breach quarter'
    end as recommended_action,
    first_breach_quarter,
    {{ quarter_number('first_breach_quarter') }} - {{ quarter_number('snapshot_quarter') }} as quarters_to_breach,
    first_critical_quarter,
    n_quarters_baseline_over,
    n_quarters_stretch_over,
    peak_baseline_saturation,
    peak_stretch_saturation,
    peak_baseline_shortfall,
    peak_stretch_shortfall
from classified
