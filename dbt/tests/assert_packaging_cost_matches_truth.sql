-- Packaging cost per product = sum(std price per piece x pieces per product) over its BOM,
-- recomputed from the ground truth (std prices of the latest fiscal year, in EUR per 1000).
-- Returns products where int_pf_packaging_cost differs. Products using a std price that
-- staging had to impute (blank in the raw data) are skipped: the truth there is unknowable.

with truth_std as (

    select snapshot_quarter, ac_code, std_price_eur_per_1000::numeric / 1000 as std_price,
           row_number() over (partition by snapshot_quarter, ac_code order by fiscal_year desc) as row_num
    from {{ source('ground_truth', 'std_prices') }}

),

truth_cost as (

    select b.snapshot_quarter, b.pf_code,
           sum(s.std_price * b.qty_per_pf::numeric)  as packaging_cost,
           count(s.ac_code) = count(*)               as complete
    from {{ source('ground_truth', 'bom') }} b
    left join truth_std s
        on  s.snapshot_quarter = b.snapshot_quarter
        and s.ac_code = b.ac_code
        and s.row_num = 1
    group by 1, 2

)

select c.snapshot_quarter, c.pf_code, c.packaging_cost_eur_per_unit, t.packaging_cost as truth_cost
from {{ ref('int_pf_packaging_cost') }} c
full join truth_cost t
    on  t.snapshot_quarter = c.snapshot_quarter
    and t.pf_code = c.pf_code
where (c.pf_code is null or t.pf_code is null)
   or (not coalesce(c.uses_imputed_std_price, false)
       and (c.has_full_packaging_cost is distinct from t.complete
            or abs(c.packaging_cost_eur_per_unit - round(t.packaging_cost, 4)) > 0.0001))
