-- Line capacities from the buyer file, checked against what the plant actually produced.
-- Grain: snapshot_quarter x line_id.
--
-- Monthly entries: buyers sometimes type a monthly figure in the "per quarter" column.
-- A line can't keep producing above its capacity, so if past production of the AC was
-- above the entered capacity in more than half of the history quarters, the figure is
-- read as monthly and multiplied by 3. Occasional peaks above capacity are real
-- saturation and are left alone. Only single-line ACs are corrected: with several lines
-- we can't tell which one is wrong, so those are only flagged.

with capacity as (

    select * from {{ ref('stg_buyer_capacity') }}

),

ac_production as (

    select
        p.snapshot_quarter,
        b.ac_code,
        p.quarter,
        sum(p.qty_produced * b.qty_per_pf) as qty_produced
    from {{ ref('stg_site_production') }} p
    join {{ ref('stg_site_bom_moq') }} b
        on  b.snapshot_quarter = p.snapshot_quarter
        and b.plant = p.plant
        and b.pf_code = p.pf_code
    group by 1, 2, 3

),

ac_capacity as (

    select
        snapshot_quarter,
        ac_code,
        sum(capacity_per_quarter) as entered_capacity,
        count(*)                  as n_lines
    from capacity
    group by 1, 2

),

ac_check as (

    select
        c.snapshot_quarter,
        c.ac_code,
        c.n_lines,
        count(p.quarter)                                       as n_history_quarters,
        count(p.quarter) filter (where p.qty_produced > c.entered_capacity) as n_quarters_over_capacity
    from ac_capacity c
    left join ac_production p
        on  p.snapshot_quarter = c.snapshot_quarter
        and p.ac_code = c.ac_code
    group by 1, 2, 3

),

flagged as (

    select
        snapshot_quarter,
        ac_code,
        n_lines,
        n_quarters_over_capacity,
        n_history_quarters,
        n_quarters_over_capacity > n_history_quarters / 2.0 as is_suspected_monthly_entry
    from ac_check

)

select
    c.*,
    f.is_suspected_monthly_entry,
    f.is_suspected_monthly_entry and f.n_lines = 1             as is_capacity_corrected,
    c.capacity_per_quarter
        * case when f.is_suspected_monthly_entry and f.n_lines = 1 then 3 else 1 end
                                                               as capacity_per_quarter_checked
from capacity c
join flagged f
    on  f.snapshot_quarter = c.snapshot_quarter
    and f.ac_code = c.ac_code
