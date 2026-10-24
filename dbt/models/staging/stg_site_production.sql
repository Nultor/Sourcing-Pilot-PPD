-- Quantities produced per finished product (PF) and past quarter at the plant.
-- Grain: snapshot_quarter x plant x pf_code x quarter.

select
    snapshot_quarter,
    trim(plant)                       as plant,
    {{ clean_code('pf_code') }}       as pf_code,
    trim(quarter)                     as quarter,
    {{ to_numeric('qty_produced') }}  as qty_produced
from {{ source('raw', 'site_production') }}
