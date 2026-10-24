-- Finance standard price per component (AC) and fiscal year.
-- Grain: snapshot_quarter x ac_code x fiscal_year.

with typed as (

    select
        snapshot_quarter,
        {{ clean_code('ac_code') }}                    as ac_code,
        nullif(trim(ac_description), '')               as ac_description,
        {{ to_numeric('fiscal_year') }}::int           as fiscal_year,
        {{ to_numeric('std_price_eur_1000') }} / 1000  as std_price_eur_per_piece
    from {{ source('raw', 'finance_std_cost') }}

)

-- A blank standard price can't be recovered exactly: use the AC's price from the
-- closest other fiscal year as an explicit assumption (is_std_price_imputed = true).
select
    t.snapshot_quarter,
    t.ac_code,
    t.ac_description,
    t.fiscal_year,
    coalesce(
        t.std_price_eur_per_piece,
        (
            select o.std_price_eur_per_piece
            from typed o
            where o.snapshot_quarter = t.snapshot_quarter
              and o.ac_code = t.ac_code
              and o.fiscal_year <> t.fiscal_year
              and o.std_price_eur_per_piece is not null
            order by abs(o.fiscal_year - t.fiscal_year)
            limit 1
        )
    )                                    as std_price_eur_per_piece,
    t.std_price_eur_per_piece is null    as is_std_price_imputed
from typed t
