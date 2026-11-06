{{ config(materialized='table') }}
-- Velas cerradas con retorno diario, retorno a 30 días y volatilidad móvil de 30 días.
-- volatilidad_30d_pct = desviación estándar de los retornos diarios de 30 días (no anualizada).
with velas as (
    select par, fecha, cierre, volumen_cotizado
    from {{ ref('stg_binance_klines') }}
    where vela_cerrada
),
retornos as (
    select
        *,
        (cierre / lag(cierre, 1)  over w - 1) * 100 as retorno_diario_pct,
        (cierre / lag(cierre, 30) over w - 1) * 100 as retorno_30d_pct
    from velas
    window w as (partition by par order by fecha)
)
select
    *,
    stddev_samp(retorno_diario_pct) over (
        partition by par order by fecha rows between 29 preceding and current row
    ) as volatilidad_30d_pct
from retornos
