FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DAGSTER_HOME=/opt/dagster/home

WORKDIR /app

# Dependencias primero: esta capa se reutiliza mientras requirements.txt no cambie.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Usuario sin privilegios; las carpetas de datos y estado le pertenecen
# para que los volúmenes de Docker hereden ese dueño.
RUN useradd --create-home --uid 1000 app \
 && mkdir -p "$DAGSTER_HOME" /opt/dagster/state /app/data \
 && cp docker/dagster.yaml "$DAGSTER_HOME/dagster.yaml" \
 && chown -R app:app /app /opt/dagster
USER app

# Genera el manifest de dbt que Dagster necesita para dibujar los modelos.
RUN cd dbt && dbt parse --profiles-dir .

EXPOSE 3000
