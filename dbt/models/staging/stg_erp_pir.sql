-- ERP purchasing info records (PIR): price and conditions per component x supplier x plant.
-- Grain: snapshot_quarter x pir_no.
-- Prices are converted to EUR per piece with the finance rate of the snapshot quarter.

with source as (

    select * from {{ source('raw', 'erp_pir') }}

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
        trim(pir_no)                         as pir_no,
        {{ clean_code('ac_code') }}          as ac_code,
        nullif(trim(supplier), '')           as supplier_raw,
        trim(plant)                          as plant,
        {{ to_numeric('net_price') }}        as net_price,
        upper(trim(currency))                as currency,
        {{ to_numeric('price_unit') }}       as price_unit,
        nullif(trim(valid_from), '')::date   as valid_from,
        nullif(trim(valid_to), '')::date     as valid_to,
        {{ to_numeric('lead_time_days') }}   as lead_time_days,
        {{ to_numeric('min_order_qty') }}    as min_order_qty,
        upper(trim(deletion_flag)) = 'X'     as is_deleted
    from source

)

select
    t.snapshot_quarter,
    t.pir_no,
    t.ac_code,
    t.supplier_raw,
    a.canonical_supplier                            as supplier,
    t.plant,
    t.net_price,
    t.currency,
    t.price_unit,
    t.net_price / nullif(t.price_unit, 0) * fx.rate_to_eur as price_eur_per_piece,
    t.valid_from,
    t.valid_to,
    t.lead_time_days,
    t.min_order_qty,
    t.is_deleted
from typed t
left join aliases a
    on a.alias = {{ supplier_key('t.supplier_raw') }}
left join fx
    on  fx.snapshot_quarter = t.snapshot_quarter
    and fx.quarter = t.snapshot_quarter
    and fx.currency = t.currency
