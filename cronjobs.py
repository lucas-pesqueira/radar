"""Crea (o actualiza) en cron-job.org las dos tareas que disparan las Actions de radar-datos a horario.

El cron de GitHub no es confiable (puede atrasarse horas o saltearse). cron-job.org dispara
las Actions por la API de GitHub (workflow_dispatch) en el minuto exacto:
  - tanda: lunes a viernes 6:47 ART
  - envio: lunes a viernes cada 15 minutos, de 11:02 a 19:47 ART

Uso (una sola vez):
    py cronjobs.py            pide las dos claves (no se muestran) y crea o actualiza las tareas
    py cronjobs.py --probar   además dispara la Action envio una vez para comprobar que la clave de GitHub anda

Las claves no se guardan en ningún archivo: quedan solo en cron-job.org (la de GitHub) y en tu memoria.
"""

import getpass
import json
import sys
import time

import requests

REPO = "lucas-pesqueira/radar-datos"
ZONA = "America/Argentina/Buenos_Aires"
API_CRON = "https://api.cron-job.org"
LUNES_A_VIERNES = [1, 2, 3, 4, 5]

TAREAS = {
    "Tinko - tanda": {"workflow": "tanda.yml", "hours": [6], "minutes": [47]},
    "Tinko - envio": {"workflow": "envio.yml", "hours": list(range(11, 20)), "minutes": [2, 17, 32, 47]},
}


def url_dispatch(workflow):
    return f"https://api.github.com/repos/{REPO}/actions/workflows/{workflow}/dispatches"


def cabeceras_github(token_github):
    return {"Authorization": f"Bearer {token_github}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"}


def armar_tarea(titulo, datos, token_github):
    """El job tal como lo pide la API de cron-job.org."""
    return {
        "title": titulo,
        "url": url_dispatch(datos["workflow"]),
        "enabled": True,
        "saveResponses": True,
        "requestMethod": 1,                                     # POST
        "requestTimeout": 30,
        "schedule": {"timezone": ZONA, "expiresAt": 0, "hours": datos["hours"], "mdays": [-1],
                     "minutes": datos["minutes"], "months": [-1], "wdays": LUNES_A_VIERNES},
        "extendedData": {"headers": cabeceras_github(token_github), "body": json.dumps({"ref": "main"})},
        "notification": {"onFailure": True, "onFailureCount": 1, "onSuccess": False, "onDisable": True},
    }


def cron(metodo, ruta, clave, **kw):
    """Llama a la API de cron-job.org. Respeta su límite (1 creación por segundo) y reintenta si se pasa."""
    for intento in range(5):
        time.sleep(2)
        r = requests.request(metodo, API_CRON + ruta, timeout=30,
                             headers={"Authorization": f"Bearer {clave}", "Content-Type": "application/json"}, **kw)
        if r.status_code != 429:
            break
        time.sleep(15 * (intento + 1))
    if r.status_code >= 300:
        sys.exit(f"cron-job.org respondió {r.status_code}: {r.text[:300]}")
    return r.json() if r.text.strip() else {}


def probar_github(token_github):
    r = requests.post(url_dispatch("envio.yml"), headers=cabeceras_github(token_github),
                      json={"ref": "main"}, timeout=30)
    if r.status_code != 204:
        sys.exit(f"GitHub respondió {r.status_code}: {r.text[:300]}\n"
                 "Revisá que la clave de GitHub tenga acceso a radar-datos con permiso Actions: Read and write.")
    print("GitHub OK: se disparó la Action envio (mirala en radar-datos → Actions).")


def main():
    clave_cron = getpass.getpass("Clave de API de cron-job.org (no se ve al pegar): ").strip()
    token_github = getpass.getpass("Clave de GitHub (fine-grained, no se ve al pegar): ").strip()
    if not clave_cron or not token_github:
        sys.exit("Faltan claves.")
    if "--probar" in sys.argv:
        probar_github(token_github)
    existentes = {j.get("title"): j["jobId"] for j in cron("GET", "/jobs", clave_cron).get("jobs", [])}
    for titulo, datos in TAREAS.items():
        job = armar_tarea(titulo, datos, token_github)
        if titulo in existentes:
            cron("PATCH", f"/jobs/{existentes[titulo]}", clave_cron, json={"job": job})
            print(f"Actualizada: {titulo}")
        else:
            r = cron("PUT", "/jobs", clave_cron, json={"job": job})
            print(f"Creada: {titulo} (id {r.get('jobId')})")
    print("Listo. Las tareas quedan en console.cron-job.org; si alguna falla, cron-job.org te avisa por mail.")


if __name__ == "__main__":
    main()
