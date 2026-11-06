{{ config(materialized='table') }}
-- Una fila por día hábil con tipo de cambio, tasas, inflación y tasa real.
-- tasa_real_tiie_pct usa Fisher: ((1+TIIE)/(1+inflación) - 1) * 100.
with fx as (
    select fecha, valor as usd_mxn
    from {{ ref('stg_banxico_series') }}
    where serie = 'tipo_cambio_fix_usd_mxn'
),
tiie as (
    select fecha, valor as tiie_28_pct
    from {{ ref('stg_banxico_series') }}
    where serie = 'tiie_28_dias'
),
base as (
    select
        fx.fecha,
        fx.usd_mxn,
        tiie.tiie_28_pct,
        lag(fx.usd_mxn, 1)  over (order by fx.fecha) as usd_mxn_ayer,
        lag(fx.usd_mxn, 21) over (order by fx.fecha) as usd_mxn_hace_21_habiles
    from fx
    left join tiie using (fecha)
)
select
    b.fecha,
    b.usd_mxn,
    (b.usd_mxn / b.usd_mxn_ayer - 1) * 100             as var_diaria_pct,
    (b.usd_mxn / b.usd_mxn_hace_21_habiles - 1) * 100  as var_21_habiles_pct,
    b.tiie_28_pct,
    c.cetes_28_pct,
    i.inflacion_anual_pct,
    ((1 + b.tiie_28_pct / 100) / (1 + i.inflacion_anual_pct / 100) - 1) * 100
                                                       as tasa_real_tiie_pct
from base b
asof left join {{ ref('int_cetes_disponible') }} c
    on b.fecha >= c.disponible_desde
asof left join {{ ref('int_inflacion_anual') }} i
    on b.fecha >= i.disponible_desde
