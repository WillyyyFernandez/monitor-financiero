-- Falla si una vela tiene precios imposibles (máximo < mínimo, o cierre fuera del rango).
select * from {{ ref('stg_binance_klines') }}
where maximo < minimo or cierre > maximo or cierre < minimo or cierre <= 0
