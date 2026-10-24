-- Buyer-maintained capacity file: one row per production line making a component (AC),
-- with the contract manufacturer (CM) that could take extra volume.
-- Grain: snapshot_quarter x line_id. All capacities in pieces per quarter.

with source as (

    select * from {{ source('raw', 'buyer_capacity_file') }}

),

aliases as (

    select * from {{ ref('supplier_alias_map') }}

),

typed as (

    select
        snapshot_quarter,
        {{ clean_code('ac') }}                             as ac_code,
        nullif(trim(description), '')                      as ac_description,
        nullif(trim(supplier), '')                         as supplier_raw,
        upper(split_part(trim(line), '-', 1))              as supplier_id,
        nullif(trim(technology), '')                       as technology,
        upper(trim(line))                                  as line_id,
        {{ to_numeric('capacity_quarter') }}               as capacity_entered,
        lower(trim(unit))                                  as unit_entered,
        nullif(trim(cm), '')                               as cm_raw,
        {{ to_numeric('cm_available_capacity_quarter') }}  as cm_available_capacity_per_quarter,
        {{ to_bool('cm_qualified') }}                      as cm_qualified,
        nullif(trim(last_update), '')::date                as last_update,
        nullif(trim(comment), '')                          as comment
    from source

)

select
    t.snapshot_quarter,
    t.ac_code,
    t.ac_description,
    t.supplier_id,
    t.supplier_raw,
    sup.canonical_supplier                       as supplier,
    t.technology,
    t.line_id,
    -- buyers type some lines in thousands of pieces
    t.capacity_entered * case t.unit_entered
                             when 'pcs'  then 1
                             when 'kpcs' then 1000
                         end                     as capacity_per_quarter,
    t.capacity_entered,
    t.unit_entered,
    cm.canonical_supplier                        as cm,
    t.cm_available_capacity_per_quarter,
    coalesce(t.cm_qualified, false)              as cm_qualified,
    t.last_update,
    t.comment
from typed t
left join aliases sup on sup.alias = {{ supplier_key('t.supplier_raw') }}
left join aliases cm  on cm.alias  = {{ supplier_key('t.cm_raw') }}
