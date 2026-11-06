{{ config(materialized='table') }}
-- Cruce Binance x Banxico: ¿el mercado cripto mexicano paga de más o de menos
-- frente al tipo de cambio oficial?
--   precio_mxn_via_fix = precio en USDT x FIX vigente
--   prima_vs_fix_pct   = precio directo en pesos / precio_mxn_via_fix - 1
-- Notas de alineación:
--   * Las velas de Binance cierran a las 00:00 UTC (18:00 CDMX); el FIX se determina
--     alrededor del mediodía CDMX. Esa diferencia horaria es parte del ruido.
--   * USDT no vale exactamente 1 USD; la prima incluye esa desviación.
with velas as (
    select par, fecha, cierre
    from {{ ref('mart_cripto_diario') }}
),
activos as (
    select
        v_usd.fecha,
        replace(v_usd.par, 'USDT', '') as activo,
        v_usd.cierre                    as precio_usdt,
        v_mxn.cierre                    as precio_mxn_binance
    from velas v_usd
    left join velas v_mxn
        on v_mxn.fecha = v_usd.fecha
       and v_mxn.par = replace(v_usd.par, 'USDT', 'MXN')
    where v_usd.par in ('BTCUSDT', 'ETHUSDT')
    union all
    -- USDT contra el peso: el dólar digital frente al dólar oficial
    select fecha, 'USDT', 1.0, cierre
    from velas
    where par = 'USDTMXN'
)
select
    a.fecha,
    a.activo,
    fx.tipo_dia,
    fx.dias_desde_fix,
    fx.usd_mxn_fix,
    a.precio_usdt,
    a.precio_mxn_binance,
    a.precio_usdt * fx.usd_mxn_fix                                       as precio_mxn_via_fix,
    (a.precio_mxn_binance / (a.precio_usdt * fx.usd_mxn_fix) - 1) * 100  as prima_vs_fix_pct
from activos a
join {{ ref('int_fix_diario') }} fx using (fecha)
where fx.usd_mxn_fix is not null
