-- Plant bill of materials: which components (AC) go into each finished product (PF), plus MOQ.
-- Grain: snapshot_quarter x plant x pf_code x ac_code.

with source as (

    select * from {{ source('raw', 'site_bom_moq') }}

),

aliases as (

    select * from {{ ref('supplier_alias_map') }}

)

select
    s.snapshot_quarter,
    trim(s.plant)                     as plant,
    {{ clean_code('s.pf_code') }}     as pf_code,
    {{ clean_code('s.ac_code') }}     as ac_code,
    nullif(trim(s.ac_description), '') as ac_description,
    {{ to_numeric('s.qty_per_pf') }}  as qty_per_pf,
    nullif(trim(s.material), '')      as material,
    nullif(trim(s.supplier), '')      as supplier_raw,
    a.canonical_supplier              as supplier,
    {{ to_numeric('s.moq_pcs') }}     as moq_pcs
from source s
left join aliases a
    on a.alias = {{ supplier_key('s.supplier') }}
