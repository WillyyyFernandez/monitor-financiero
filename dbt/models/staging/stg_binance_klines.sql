-- Una fila por par y día (UTC). Las velas de Binance abren a las 00:00 UTC.
-- Las corridas incrementales repiten las últimas velas; se toma la carga más reciente.
with ultima_version as (
    select *
    from {{ source('bronze', 'binance_klines') }}
    qualify row_number() over (partition by par, open_time_ms order by cargado_en desc) = 1
)
select
    par,
    (to_timestamp(open_time_ms / 1000.0) at time zone 'UTC')::date as fecha,
    cast(open  as double) as apertura,
    cast(high  as double) as maximo,
    cast(low   as double) as minimo,
    cast(close as double) as cierre,
    cast(volume as double) as volumen_base,
    cast(quote_volume as double) as volumen_cotizado,
    trades as operaciones,
    -- la vela del día en curso aún no cierra y se reescribe en cada corrida
    close_time_ms < epoch_ms(now()) as vela_cerrada,
    cargado_en
from ultima_version
