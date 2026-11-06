-- Un día por fila desde 2020-01-01 hasta hoy, con su clasificación bancaria.
-- Los feriados se infieren de los datos: un día entre semana sin FIX publicado.
-- Solo se marca feriado hasta el último FIX conocido; los días posteriores quedan
-- 'pendiente' (p. ej. hoy, antes de que Banxico publique el FIX).
with dias as (
    select unnest(generate_series(date '2020-01-01', current_date, interval 1 day))::date as fecha
),
fix as (
    select fecha
    from {{ ref('stg_banxico_series') }}
    where serie = 'tipo_cambio_fix_usd_mxn'
),
ultimo_fix as (
    select max(fecha) as fecha from fix
)
select
    d.fecha,
    year(d.fecha)          as anio,
    month(d.fecha)         as mes,
    isodow(d.fecha)        as dia_semana_iso,   -- 1 = lunes ... 7 = domingo
    isodow(d.fecha) >= 6   as es_fin_de_semana,
    f.fecha is not null    as es_dia_habil_banxico,
    case
        when f.fecha is not null                       then 'habil'
        when isodow(d.fecha) >= 6                      then 'fin_de_semana'
        when d.fecha > (select fecha from ultimo_fix)  then 'pendiente'
        else 'feriado_bancario'
    end as tipo_dia
from dias d
left join fix f using (fecha)
