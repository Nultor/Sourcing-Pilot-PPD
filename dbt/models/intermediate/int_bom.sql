-- Full bill of materials: products in production (plant BOM) + products in the launch pipeline (NPD).
-- Grain: snapshot_quarter x pf_code x ac_code.

select
    snapshot_quarter,
    pf_code,
    ac_code,
    qty_per_pf,
    'site_bom' as bom_source
from {{ ref('stg_site_bom_moq') }}

union all

-- an NPD that has reached the plant BOM is taken from there only
select
    n.snapshot_quarter,
    n.pf_code,
    n.ac_code,
    n.qty_per_pf,
    'npd' as bom_source
from {{ ref('stg_npd_projects') }} n
where not exists (
    select 1
    from {{ ref('stg_site_bom_moq') }} s
    where s.snapshot_quarter = n.snapshot_quarter
      and s.pf_code = n.pf_code
)
