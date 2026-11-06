-- Tipo de cambio FIX vigente para TODOS los días del calendario.
-- Decisión: en fines de semana y feriados se usa el último FIX publicado, que es
-- el que rige en esos días. dias_desde_fix deja explícito cuánto tiene de antigüedad.
select
    c.fecha,
    c.tipo_dia,
    f.fecha             as fecha_fix,
    f.valor             as usd_mxn_fix,
    c.fecha - f.fecha   as dias_desde_fix
from {{ ref('int_calendario') }} c
asof left join (
    select fecha, valor
    from {{ ref('stg_banxico_series') }}
    where serie = 'tipo_cambio_fix_usd_mxn'
) f on c.fecha >= f.fecha
