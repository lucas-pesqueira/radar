"""Cliente mínimo de la API de Apify: arrancar un actor, esperar y bajar resultados."""

import hashlib
import time

import requests

API = "https://api.apify.com/v2"
TERMINADOS = {"SUCCEEDED", "FAILED", "TIMED-OUT", "ABORTED"}


class ErrorApify(Exception):
    pass


class Apify:
    def __init__(self, token, sesion=None):
        self.s = sesion or requests.Session()
        self.s.headers["Authorization"] = "Bearer " + token

    def _pedir(self, metodo, ruta, reintentos=4, **kw):
        ultimo = None
        for intento in range(reintentos):
            try:
                r = self.s.request(metodo, API + ruta, timeout=60, **kw)
            except requests.RequestException as e:
                ultimo = str(e)
                time.sleep(3 * (intento + 1))
                continue
            if r.status_code == 401:
                raise ErrorApify("El token de Apify no es válido. Revisalo en Apify > Settings > API & Integrations.")
            if r.status_code == 429 or r.status_code >= 500:
                ultimo = f"HTTP {r.status_code}"
                time.sleep(5 * (intento + 1))
                continue
            if r.status_code >= 400:
                try:
                    msg = r.json().get("error", {}).get("message", r.text)
                except ValueError:
                    msg = r.text
                raise ErrorApify(f"Apify respondió {r.status_code}: {msg}")
            return r.json()
        raise ErrorApify(f"No se pudo hablar con Apify ({ultimo}). Revisá tu conexión y volvé a correr.")

    def credito(self):
        """Devuelve (usado, maximo) del mes en USD, o (None, None) si no se puede leer."""
        try:
            d = self._pedir("GET", "/users/me/limits").get("data", {})
            usado = d.get("current", {}).get("monthlyUsageUsd")
            maximo = d.get("limits", {}).get("maxMonthlyUsageUsd")
            return usado, maximo
        except ErrorApify:
            return None, None

    def arrancar(self, actor, entrada, tope_usd):
        params = {"maxTotalChargeUsd": round(tope_usd, 2)}
        d = self._pedir("POST", f"/acts/{actor}/runs", params=params, json=entrada)
        return d["data"]

    def corrida(self, run_id):
        return self._pedir("GET", f"/actor-runs/{run_id}")["data"]

    def esperar(self, run_id, al_avanzar=None, cada=15):
        while True:
            run = self.corrida(run_id)
            if run["status"] in TERMINADOS:
                return run
            if al_avanzar:
                al_avanzar(run)
            time.sleep(cada)

    def items(self, dataset_id):
        todos, offset, lote = [], 0, 500
        while True:
            r = self._pedir("GET", f"/datasets/{dataset_id}/items",
                            params={"clean": "true", "format": "json", "offset": offset, "limit": lote})
            if not isinstance(r, list):
                raise ErrorApify("Respuesta inesperada al bajar resultados.")
            todos.extend(r)
            if len(r) < lote:
                return todos
            offset += lote


class Cuentas:
    """Varias cuentas de Apify (una por token), en orden. Usa la primera que tenga crédito para lo
    que hace falta y, si se queda corta, pasa a la siguiente. Nunca muestra los tokens: cada cuenta
    se identifica por su número de orden y por un id corto (huella del token)."""

    def __init__(self, lista, fabrica=None, avisar=print):
        fabrica = fabrica or Apify
        self.cuentas = []
        for i, t in enumerate(lista, 1):
            api = fabrica(t)
            usado, maximo = api.credito()
            if usado is None or not maximo:
                avisar(f"  Cuenta de Apify {i}: no responde o el token no es válido (se saltea).")
                continue
            self.cuentas.append({"n": i, "id": hashlib.sha256(t.encode()).hexdigest()[:10], "api": api,
                                 "libre": maximo - usado, "usado": usado, "maximo": maximo})

    def libre_total(self):
        return round(sum(max(c["libre"], 0) for c in self.cuentas), 2)

    def para(self, costo):
        """La primera cuenta con crédito para 'costo' (lo descuenta), o None."""
        for c in self.cuentas:
            if c["libre"] >= costo:
                c["libre"] -= costo
                return c
        return None

    def por_id(self, cid):
        return next((c for c in self.cuentas if c["id"] == cid), None)
