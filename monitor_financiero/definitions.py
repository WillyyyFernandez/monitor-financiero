import json
import sys
from pathlib import Path

from dagster import (
    AssetKey,
    AssetSelection,
    DefaultScheduleStatus,
    Definitions,
    Failure,
    MaterializeResult,
    MetadataValue,
    ScheduleDefinition,
    asset,
    define_asset_job,
    in_process_executor,
    job,
    op,
)
from dagster_dbt import DbtCliResource, DbtProject, dbt_assets
from dotenv import load_dotenv

from ingesta import banxico, binance

RAIZ = Path(__file__).parent.parent
load_dotenv(RAIZ / ".env")

DBT_DIR = RAIZ / "dbt"
dbt_project = DbtProject(project_dir=DBT_DIR, profiles_dir=DBT_DIR)
dbt_project.prepare_if_dev()


# Las claves coinciden con source('bronze', ...) de dbt, así Dagster dibuja cada
# ingesta como padre de su modelo de staging.
@asset(key=AssetKey(["bronze", "banxico_series"]), group_name="ingesta")
def banxico_series(context):
    resumen = banxico.sincronizar()
    context.log.info(f"bronze banxico: {resumen}")
    return MaterializeResult(metadata={"filas": resumen["filas"], "archivo": resumen["archivo"]})


@asset(key=AssetKey(["bronze", "binance_klines"]), group_name="ingesta")
def binance_klines(context):
    resumen = binance.sincronizar()
    context.log.info(f"velas descargadas por par: {resumen}")
    return MaterializeResult(metadata={"velas_descargadas": sum(resumen.values())})


@dbt_assets(manifest=dbt_project.manifest_path)
def dbt_models(context, dbt: DbtCliResource):
    yield from dbt.cli(["build"], context=context).stream()


# Revisión independiente de la frescura de carga. Corre lejos del pipeline para
# detectar justo lo que el pipeline no puede: que la corrida de las 13:00 no
# haya ocurrido (NUC apagada, daemon caído, ingesta fallando varios días).
@op
def revisar_frescura_fuentes(context, dbt: DbtCliResource):
    invocacion = dbt.cli(["source", "freshness"], raise_on_error=False)
    invocacion.wait()
    resultados = json.loads(invocacion.target_path.joinpath("sources.json").read_text())["results"]
    resumen = {
        r["unique_id"].split(".")[-1]: {
            "estado": r["status"],
            "horas_desde_carga": round(r.get("max_loaded_at_time_ago_in_s", 0) / 3600, 1),
        }
        for r in resultados
    }
    context.add_output_metadata({"fuentes": MetadataValue.json(resumen)})
    for nombre, r in resumen.items():
        context.log.info(f"{nombre}: {r['estado']} ({r['horas_desde_carga']} h desde la última carga)")
    malas = {n: r for n, r in resumen.items() if r["estado"] in ("error", "runtime error")}
    if malas:
        raise Failure(description=f"Fuentes sin cargas recientes: {malas}")
    return resumen


@job
def revision_frescura():
    revisar_frescura_fuentes()


job_diario = define_asset_job("pipeline_diario", selection=AssetSelection.all())
# 13:00 CDMX: Banxico determina el FIX alrededor del mediodía, así cada corrida
# trae el FIX del mismo día. La vela diaria de Binance ya cerró (18:00 CDMX del día anterior).
programacion_diaria = ScheduleDefinition(
    job=job_diario, cron_schedule="0 13 * * *", execution_timezone="America/Mexico_City",
    default_status=DefaultScheduleStatus.RUNNING,  # activa sin tocar la interfaz
)
programacion_frescura = ScheduleDefinition(
    job=revision_frescura, cron_schedule="0 20 * * *", execution_timezone="America/Mexico_City",
    default_status=DefaultScheduleStatus.RUNNING,
)

defs = Definitions(
    assets=[banxico_series, binance_klines, dbt_models],
    jobs=[job_diario, revision_frescura],
    executor=in_process_executor,  # DuckDB admite un solo escritor a la vez
    schedules=[programacion_diaria, programacion_frescura],
    resources={
        "dbt": DbtCliResource(
            project_dir=dbt_project,
            dbt_executable=str(Path(sys.executable).parent / "dbt"),
        )
    },
)
