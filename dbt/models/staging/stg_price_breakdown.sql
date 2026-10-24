-- Supplier cost breakdown per component (AC), converted to EUR per piece.
-- Grain: snapshot_quarter x ac_code x supplier.

with source as (

    select * from {{ source('raw', 'price_breakdown') }}

),

aliases as (

    select * from {{ ref('supplier_alias_map') }}

),

fx as (

    select * from {{ ref('stg_finance_fx_rates') }}

),

typed as (

    select
        snapshot_quarter,
        {{ clean_code('ac') }}                 as ac_code,
        nullif(trim(supplier), '')             as supplier_raw,
        upper(trim(currency))                  as currency,
        lower(trim(unit))                      as unit_raw,
        -- 'per 1000 pcs' -> 1000, 'per pc' -> 1
        coalesce((regexp_match(lower(trim(unit)), '([0-9]+)'))[1]::numeric, 1) as price_unit,
        {{ to_numeric('raw_material') }}       as raw_material,
        {{ to_numeric('conversion') }}         as conversion,
        {{ to_numeric('decoration') }}         as decoration,
        {{ to_numeric('packaging') }}          as packaging,
        {{ to_numeric('transport') }}          as transport,
        {{ to_numeric('overhead_margin') }}    as overhead_margin,
        {{ to_numeric('total') }}              as total
    from source

),

per_piece as (

    select
        t.snapshot_quarter,
        t.ac_code,
        t.supplier_raw,
        a.canonical_supplier as supplier,
        t.currency,
        t.unit_raw,
        fx.rate_to_eur / t.price_unit as to_eur_per_piece,
        t.raw_material, t.conversion, t.decoration, t.packaging, t.transport, t.overhead_margin, t.total
    from typed t
    left join aliases a
        on a.alias = {{ supplier_key('t.supplier_raw') }}
    left join fx
        on  fx.snapshot_quarter = t.snapshot_quarter
        and fx.quarter = t.snapshot_quarter
        and fx.currency = t.currency

)

select
    snapshot_quarter,
    ac_code,
    supplier_raw,
    supplier,
    currency,
    unit_raw,
    raw_material    * to_eur_per_piece as raw_material_eur_per_piece,
    conversion      * to_eur_per_piece as conversion_eur_per_piece,
    decoration      * to_eur_per_piece as decoration_eur_per_piece,
    packaging       * to_eur_per_piece as packaging_eur_per_piece,
    transport       * to_eur_per_piece as transport_eur_per_piece,
    overhead_margin * to_eur_per_piece as overhead_margin_eur_per_piece,
    -- the stated total doesn't always equal the sum of its cost lines: the lines are
    -- taken as right, the stated total is kept for reference and the gap is flagged
    (raw_material + conversion + decoration + packaging + transport + overhead_margin)
                    * to_eur_per_piece as total_eur_per_piece,
    total           * to_eur_per_piece as total_stated_eur_per_piece,
    abs(total - (raw_material + conversion + decoration + packaging + transport + overhead_margin)) > 0.02
                                       as is_total_inconsistent
from per_piece
