-- Falla si algún valor sale de rangos económicamente razonables.
select * from {{ ref('mart_indicadores_diarios') }}
where usd_mxn not between 10 and 40
   or tiie_28_pct not between 0 and 30
   or inflacion_anual_pct not between -5 and 30
   or abs(var_diaria_pct) > 10
