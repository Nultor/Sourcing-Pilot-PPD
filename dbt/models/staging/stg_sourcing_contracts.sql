-- Supply contracts per component (AC) x supplier.
-- Grain: snapshot_quarter x ac_code x supplier.

with source as (

    select * from {{ source('raw', 'sourcing_contracts') }}

),

aliases as (

    select * from {{ ref('supplier_alias_map') }}

)

select
    s.snapshot_quarter,
    {{ clean_code('s.ac_code') }}             as ac_code,
    nullif(trim(s.supplier), '')              as supplier_raw,
    a.canonical_supplier                      as supplier,
    nullif(trim(s.contract_start), '')::date  as contract_start,
    nullif(trim(s.contract_end), '')::date    as contract_end,
    nullif(trim(s.last_rfq_date), '')::date   as last_rfq_date
from source s
left join aliases a
    on a.alias = {{ supplier_key('s.supplier') }}
