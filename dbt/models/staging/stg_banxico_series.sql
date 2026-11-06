-- Una fila por serie y fecha, con tipos correctos y nombre legible.
-- bronze guarda una foto completa por descarga; aquí se toma la más reciente
-- de cada (serie, fecha), así una revisión de Banxico reemplaza al dato viejo.
with ultima_version as (
    select *
    from {{ source('bronze', 'banxico_series') }}
    qualify row_number() over (partition by id_serie, fecha order by cargado_en desc) = 1
)
select
    id_serie,
    case id_serie
        when 'SF43718' then 'tipo_cambio_fix_usd_mxn'
        when 'SF43783' then 'tiie_28_dias'
        when 'SF282'   then 'cetes_28_dias'
        when 'SP1'     then 'inpc_indice_general'
    end as serie,
    strptime(fecha, '%d/%m/%Y')::date as fecha,
    cast(dato as double) as valor,
    cargado_en
from ultima_version
