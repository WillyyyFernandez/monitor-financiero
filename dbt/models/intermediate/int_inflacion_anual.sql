-- Inflación anual (%) = INPC del mes / INPC del mismo mes un año antes - 1.
-- "disponible_desde" aproxima cuándo se conoce el dato: el primer día del mes
-- siguiente. Así evitamos usar en el mercado un dato que aún no se publicaba.
with inpc as (
    select fecha, valor
    from {{ ref('stg_banxico_series') }}
    where serie = 'inpc_indice_general'
)
select
    a.fecha                                   as mes,
    a.fecha + interval 1 month                as disponible_desde,
    (a.valor / b.valor - 1) * 100             as inflacion_anual_pct
from inpc a
join inpc b on b.fecha = a.fecha - interval 12 month
