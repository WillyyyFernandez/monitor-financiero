# Monitor financiero de México

Pipeline de datos de punta a punta: ingesta diaria de Banxico (tipo de cambio FIX,
TIIE, CETES, INPC) y Binance (BTC, ETH, USDT en dólares y pesos), modelado con dbt
sobre DuckDB y orquestación con Dagster.

```
                      bronze (Parquet inmutable)     staging (dbt)          marts (dbt)
Banxico SIE ──► data/bronze/banxico_series/ ──► stg_banxico_series ─ int_* ─ mart_indicadores_diarios
Binance     ──► data/bronze/binance_klines/ ──► stg_binance_klines ──────── mart_cripto_diario
```

Cada descarga se guarda como un Parquet nuevo en
`data/bronze/<fuente>/fecha_carga=AAAA-MM-DD/`, y nunca se reescribe. Staging se
queda con la versión más reciente de cada dato, así una revisión de Banxico
reemplaza al valor viejo sin perder el historial de lo que se publicó.

## Estructura

| Carpeta | Contenido |
|---|---|
| `ingesta/` | Descarga a bronze (Banxico completo, Binance incremental) y reintentos HTTP |
| `dbt/` | Modelos `staging`, `intermediate`, `marts` y tests de calidad |
| `monitor_financiero/` | Definiciones de Dagster: activos, trabajo y programación diaria (7:00 CDMX) |
| `docker/` | Configuración de la instancia de Dagster para el contenedor |

## Requisitos

- Token del [SIE de Banxico](https://www.banxico.org.mx/SieAPIRest/service/v1/token) (gratis).
- Binance no requiere llave.

Copia `.env.example` a `.env` y rellena los tokens. `.env` nunca se sube a git.

## Correr con Docker (servidor)

```bash
cp .env.example .env        # y rellena BANXICO_TOKEN
docker compose up -d --build
docker compose ps
```

- Interfaz de Dagster: `http://127.0.0.1:3000` en la propia máquina. Solo escucha en
  localhost; desde otra computadora usa un túnel SSH:
  `ssh -L 3000:127.0.0.1:3000 usuario@servidor`.
- La programación diaria queda activa al arrancar; el daemon la dispara solo.
- Las corridas se ejecutan de una en una (DuckDB admite un solo escritor).
- Los datos y el historial de Dagster viven en los volúmenes `datos` y `estado`.

Primera carga sin esperar a las 7:00:

```bash
docker compose exec webserver dagster job launch -m monitor_financiero.definitions -j pipeline_diario
```

Copiar la base de datos fuera del contenedor (respaldo o evidencia):

```bash
docker compose cp webserver:/app/data/monitor.duckdb ./monitor.duckdb
```

Si cambias `.env`, recrea los contenedores (`docker restart` no relee el archivo):

```bash
docker compose up -d --force-recreate
```

## Correr en local (desarrollo)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export DAGSTER_HOME=$PWD/.dagster && mkdir -p .dagster && touch .dagster/dagster.yaml
.venv/bin/dagster asset materialize -m monitor_financiero.definitions --select '*'
.venv/bin/dagster dev -m monitor_financiero.definitions   # interfaz en 127.0.0.1:3000
```
