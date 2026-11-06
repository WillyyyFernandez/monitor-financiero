"""GET con reintentos compartido por todas las ingestas."""
import time

import requests


def get_json(url: str, *, params: dict | None = None, headers: dict | None = None,
             intentos: int = 5, timeout: int = 60):
    """Reintenta con espera exponencial (1, 2, 4, 8 s) ante fallos de red, 429 o 5xx.

    Un 4xx distinto de 418/429 (p. ej. token inválido) falla de inmediato:
    reintentar no lo arregla.
    """
    for i in range(intentos):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code in (418, 429) or r.status_code >= 500:
                raise requests.HTTPError(f"HTTP {r.status_code}", response=r)
            r.raise_for_status()
            return r.json()
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
            reintentable = not isinstance(e, requests.HTTPError) or (
                e.response is not None
                and (e.response.status_code in (418, 429) or e.response.status_code >= 500)
            )
            if not reintentable or i == intentos - 1:
                raise
            time.sleep(2**i)
