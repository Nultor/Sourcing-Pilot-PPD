-- Finance exchange rates: 1 unit of currency = rate_to_eur EUR.
-- Grain: snapshot_quarter x currency x quarter.

select
    snapshot_quarter,
    upper(trim(currency))            as currency,
    trim(quarter)                    as quarter,
    {{ to_numeric('rate_to_eur') }}  as rate_to_eur
from {{ source('raw', 'finance_fx_rates') }}
