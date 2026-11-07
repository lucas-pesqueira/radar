"""Estudio de nichos: qué rubro y qué ciudad tienen más negocios con reseñas sin responder.

Uso (desde esta carpeta):
    py estudio.py estimar      cuánto va a costar, sin gastar nada
    py estudio.py descargar    baja los negocios y reseñas de Google Maps con Apify
    py estudio.py emails       busca el mail público en la web de cada negocio (gratis)
    py estudio.py analizar     arma las tablas y el reporte (gratis, se puede repetir)
    py estudio.py todo         descargar + emails + analizar
"""

import csv
import html
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import config as C
from analisis import construir_negocios, resumir
from apify import Apify, ErrorApify

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

BASE = Path(__file__).resolve().parent
CRUDO = BASE / "datos" / "crudo"
ESTADO = BASE / "datos" / "corridas.json"
EMAILS = BASE / "datos" / "emails.json"
TOKEN = BASE / "token_apify.txt"
RESULTADOS = BASE / "resultados"


# ---------------------------------------------------------------------------
# Archivos
# ---------------------------------------------------------------------------
def leer_json(p, defecto):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defecto


def guardar_json(p, datos):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def token():
    t = os.environ.get("APIFY_TOKEN", "").strip()
    if not t and TOKEN.exists():
        t = TOKEN.read_text(encoding="utf-8").strip()
    if not t:
        print("Pegá tu token de Apify (Apify > Settings > API & Integrations > Personal API token):")
        t = input("> ").strip()
        if not t:
            sys.exit("Sin token no se puede seguir.")
        TOKEN.write_text(t, encoding="utf-8")
        print("Guardado en token_apify.txt. No compartas ese archivo.\n")
    return t


# ---------------------------------------------------------------------------
# Costos
# ---------------------------------------------------------------------------
def entrada_apify(ciudad):
    return {
        "searchStringsArray": [r["busqueda"] for r in C.RUBROS.values()],
        "locationQuery": C.CIUDADES[ciudad]["ubicacion"],
        "maxCrawledPlacesPerSearch": C.NEGOCIOS_POR_BUSQUEDA,
        "language": "en",
        "maxReviews": C.RESENAS_POR_NEGOCIO,
        "reviewsSort": "newest",
        "scrapeReviewsPersonalData": False,
        "scrapePlaceDetailPage": False,
        "scrapeContacts": False,
        "maxImages": 0,
        "maxQuestions": 0,
    }


def costo_ciudad():
    """Peor caso en USD para una ciudad: todos los negocios con todas sus reseñas."""
    lugares = len(C.RUBROS) * C.NEGOCIOS_POR_BUSQUEDA
    pr = C.PRECIOS
    return (pr["inicio"] + lugares * (pr["lugar"] + pr["detalle"])
            + lugares * C.RESENAS_POR_NEGOCIO * pr["resena"])


def cmd_estimar(api=None):
    lugares = len(C.RUBROS) * C.NEGOCIOS_POR_BUSQUEDA
    pendientes = [c for c in C.CIUDADES if not (CRUDO / f"{c}.json").exists()]
    por_ciudad = costo_ciudad()
    total = por_ciudad * len(pendientes)
    print(f"Rubros: {len(C.RUBROS)} | Ciudades: {len(C.CIUDADES)} | "
          f"{C.NEGOCIOS_POR_BUSQUEDA} negocios por rubro y ciudad | {C.RESENAS_POR_NEGOCIO} reseñas por negocio")
    print(f"Por ciudad: hasta {lugares} negocios y {lugares * C.RESENAS_POR_NEGOCIO} reseñas, "
          f"como máximo USD {por_ciudad:.2f}")
    if len(pendientes) < len(C.CIUDADES):
        print(f"Ya descargadas: {', '.join(c for c in C.CIUDADES if c not in pendientes)} (no se vuelven a pagar)")
    print(f"Falta descargar: {len(pendientes)} ciudades -> como máximo USD {total:.2f}")
    print("(Es el peor caso: si un negocio tiene menos reseñas, cuesta menos.)")
    if api:
        usado, maximo = api.credito()
        if usado is not None and maximo:
            libre = maximo - usado
            print(f"Tu crédito de Apify este mes: usaste USD {usado:.2f} de {maximo:.2f} (quedan {libre:.2f})")
            return total, libre
    return total, None


# ---------------------------------------------------------------------------
# Descarga
# ---------------------------------------------------------------------------
def cmd_descargar(confirmar=True):
    api = Apify(token())
    total, libre = cmd_estimar(api)
    if total == 0:
        print("\nTodo descargado. Seguí con: py estudio.py analizar")
        return
    tope = libre if libre is not None else C.PRESUPUESTO_USD
    if total > tope + 1e-9:
        sys.exit(f"\nEl peor caso (USD {total:.2f}) supera el crédito disponible (USD {tope:.2f}). "
                 "Bajá NEGOCIOS_POR_BUSQUEDA o RESENAS_POR_NEGOCIO en config.py.")
    if confirmar and input("\n¿Arranco? (s/n) ").strip().lower() not in ("s", "si", "sí", "y"):
        sys.exit("Cancelado. No se gastó nada.")

    estado = leer_json(ESTADO, {})
    for ciudad in C.CIUDADES:
        destino = CRUDO / f"{ciudad}.json"
        if destino.exists():
            continue
        nombre = C.CIUDADES[ciudad]["nombre"]
        entrada = entrada_apify(ciudad)
        previo = estado.get(ciudad)
        if previo and previo.get("entrada") == entrada:
            run_id = previo["run_id"]
            print(f"\n{nombre}: retomo la corrida que ya estaba en marcha ({run_id}).")
        else:
            print(f"\n{nombre}: arrancando en Apify...")
            run = api.arrancar(C.ACTOR_MAPS, entrada, costo_ciudad() * 1.1)
            run_id = run["id"]
            estado[ciudad] = {"run_id": run_id, "entrada": entrada}
            guardar_json(ESTADO, estado)

        inicio = time.time()
        aviso = [0.0]

        def avanzar(_run):
            min_ = (time.time() - inicio) / 60
            if min_ - aviso[0] >= 1:
                aviso[0] = min_
                print(f"  {nombre}: corriendo ({min_:.0f} min)...")

        try:
            run = api.esperar(run_id, avanzar)
        except KeyboardInterrupt:
            sys.exit("\nCortado. La corrida sigue en Apify y no se pierde: "
                     "volvé a correr 'py estudio.py descargar' y la retoma sin pagarla de nuevo.")

        items = api.items(run["defaultDatasetId"])
        completa = run["status"] == "SUCCEEDED"
        guardar_json(destino, {
            "ciudad": ciudad,
            "fecha": (run.get("finishedAt") or datetime.now(timezone.utc).isoformat()),
            "run_id": run_id,
            "estado_corrida": run["status"],
            "completa": completa,
            "entrada": entrada,
            "items": items,
        })
        estado.pop(ciudad, None)
        guardar_json(ESTADO, estado)
        conteo = {}
        for it in items:
            conteo[it.get("searchString")] = conteo.get(it.get("searchString"), 0) + 1
        print(f"  {nombre}: {len(items)} negocios ({run['status']}).")
        cortos = [r["nombre"] for r in C.RUBROS.values()
                  if conteo.get(r["busqueda"], 0) < C.NEGOCIOS_POR_BUSQUEDA // 2]
        if cortos:
            print(f"  Ojo: pocos resultados en {', '.join(cortos)}.")
        if not completa:
            print("  Ojo: la corrida no terminó bien. Los datos que llegaron se guardaron igual.")
    print("\nDescarga lista.")


# ---------------------------------------------------------------------------
# Lectura del crudo
# ---------------------------------------------------------------------------
def cargar_crudo():
    crudo = {}
    for ciudad in C.CIUDADES:
        p = CRUDO / f"{ciudad}.json"
        if p.exists():
            crudo[ciudad] = leer_json(p, {})
    if not crudo:
        sys.exit("No hay datos descargados. Corré primero: py estudio.py descargar")
    faltan = [C.CIUDADES[c]["nombre"] for c in C.CIUDADES if c not in crudo]
    if faltan:
        print(f"Ojo: faltan datos de {', '.join(faltan)}. El análisis sale sin esas ciudades.")
    busquedas = {r["busqueda"] for r in C.RUBROS.values()}
    for c, b in crudo.items():
        hechas = set(b.get("entrada", {}).get("searchStringsArray", []))
        nuevas = busquedas - hechas
        if nuevas:
            print(f"Ojo: {C.CIUDADES[c]['nombre']} se descargó sin {', '.join(sorted(nuevas))}. "
                  f"Para incluirlos, borrá datos/crudo/{c}.json y volvé a descargar.")
    return crudo


# ---------------------------------------------------------------------------
# Emails
# ---------------------------------------------------------------------------
def cmd_emails():
    from emails import buscar_todos

    negocios = construir_negocios(cargar_crudo())
    webs = {}
    for n in negocios:
        if n["independiente"] and n["tipo_web"] == "propia" and n["dominio"] not in webs:
            webs[n["dominio"]] = n["web"]
    previos = leer_json(EMAILS, {})
    faltan = [d for d in webs if d not in previos]
    print(f"Webs de negocios independientes: {len(webs)} | ya revisadas: {len(webs) - len(faltan)} | "
          f"por revisar: {len(faltan)}")
    if not faltan:
        return

    def avanzar(i, total):
        if i % 25 == 0 or i == total:
            print(f"  {i}/{total} webs revisadas")

    res = buscar_todos(webs, previos, avanzar)
    guardar_json(EMAILS, res)
    con = sum(1 for d in webs if (res.get(d) or {}).get("email"))
    print(f"Listo: {con} de {len(webs)} webs tienen un mail público.")


# ---------------------------------------------------------------------------
# Análisis y salida
# ---------------------------------------------------------------------------
COLUMNAS_NEGOCIOS = [
    "rubro_nombre", "ciudad_nombre", "nombre", "puntaje", "prospecto_calificado", "porque",
    "sin_resp_reciente", "sin_resp_total", "n_muestra", "tasa_respuesta", "negativa_sin_resp",
    "negativa_estrellas", "negativa_fecha", "negativa_texto", "dejo_de_responder",
    "resenas_por_mes", "ultima_resena", "ultima_respuesta", "rating", "resenas_totales",
    "paga_anuncios", "categoria", "posicion_maps", "web", "tipo_web", "email", "telefono",
    "direccion", "maps", "independiente", "cadena", "motivo_cadena", "reclamado", "cerrado",
    "categoria_ok", "descarte", "rubro", "ciudad", "place_id",
]


def valor_csv(v):
    if v is True:
        return "si"
    if v is False:
        return "no"
    return "" if v is None else v


def escribir_csv(p, filas, columnas=None):
    columnas = columnas or (list(filas[0].keys()) if filas else [])
    with p.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=columnas, extrasaction="ignore")
        w.writeheader()
        for fila in filas:
            w.writerow({k: valor_csv(fila.get(k)) for k in columnas})


def fmt(v, sufijo=""):
    if v is None or v == "":
        return "-"
    if isinstance(v, float):
        v = f"{v:g}"
    return f"{v}{sufijo}"


TABLA = [
    ("Prospectos calificados", "pct_calificados", "%"),
    ("Con reseñas sin responder (90 días)", "pct_sin_resp_reciente", "%"),
    ("Negativa sin responder (180 días)", "pct_negativa_sin_resp", "%"),
    ("Nunca responde", "pct_nunca_responde", "%"),
    ("Responde (mediana)", "pct_respuesta_mediana", "%"),
    ("Reseñas por mes (mediana)", "resenas_mes_mediana", ""),
    ("Rating mediano", "rating_mediano", ""),
    ("Con web propia", "pct_con_web", "%"),
    ("Pagan anuncios", "pct_paga_anuncios", "%"),
    ("Cadenas descartadas", "pct_cadenas", "%"),
    ("Independientes medidos", "independientes", ""),
]


def tabla_html(filas, etiqueta, clave_nombre, extra=()):
    cols = list(TABLA) + list(extra)
    th = "".join(f"<th>{html.escape(t)}</th>" for t, _, _ in cols)
    cuerpo = ""
    for f in filas:
        tds = "".join(f"<td>{html.escape(fmt(f.get(k), s))}</td>" for _, k, s in cols)
        cuerpo += f"<tr><th>{html.escape(str(f.get(clave_nombre)))}</th>{tds}</tr>"
    return f"<table><thead><tr><th>{etiqueta}</th>{th}</tr></thead><tbody>{cuerpo}</tbody></table>"


def reporte_html(rubros, ciudades, negocios, con_emails):
    extra = [("Calificados con mail", "pct_calificados_con_email", "%")] if con_emails else []
    top = sorted((n for n in negocios if n["prospecto_calificado"]),
                 key=lambda n: (-n["puntaje"], -n["sin_resp_reciente"]))[:40]
    filas_top = ""
    for n in top:
        gancho = (f"Negativa de {n['negativa_estrellas']} estrellas sin responder ({n['negativa_fecha']}): "
                  f"\"{n['negativa_texto'][:140]}\"") if n["negativa_sin_resp"] else ""
        filas_top += (f"<tr><td>{n['puntaje']}</td><td>{html.escape(str(n['nombre']))}</td>"
                      f"<td>{html.escape(n['rubro_nombre'])}</td><td>{html.escape(n['ciudad_nombre'])}</td>"
                      f"<td>{html.escape(n['porque'])}</td><td>{html.escape(gancho)}</td></tr>")
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Estudio de nichos</title>
<style>
body{{font:14px system-ui,sans-serif;margin:24px;color:#151827;background:#f6f7fb}}
h1{{margin:0 0 4px}} h2{{margin:28px 0 8px}} p{{color:#555;max-width:80ch}}
.scroll{{overflow-x:auto;background:#fff;border:1px solid #dde;border-radius:10px}}
table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}
th,td{{padding:7px 10px;border-bottom:1px solid #eef;text-align:right;white-space:nowrap}}
thead th{{background:#f0f2f8;font-size:12px;position:sticky;top:0}}
tbody th{{text-align:left}}
.top th,.top td:nth-child(n+2){{text-align:left}} .top td:nth-child(n+5){{white-space:normal;min-width:240px}}
</style></head><body>
<h1>Estudio de nichos</h1>
<p>Generado el {datetime.now().strftime('%d/%m/%Y %H:%M')}. Los porcentajes se calculan sobre negocios
independientes y abiertos del rubro. Prospecto calificado: perfil reclamado, al menos
{C.MIN_RESENAS_MES:g} reseña por mes y {C.SIN_RESP_MIN}+ reseñas sin responder en {C.DIAS_RECIENTE} días
o una negativa sin responder en {C.DIAS_NEGATIVA} días.</p>
<h2>Por rubro</h2><div class="scroll">{tabla_html(rubros, "Rubro", "rubro_nombre", extra)}</div>
<h2>Por ciudad</h2><div class="scroll">{tabla_html(ciudades, "Ciudad", "ciudad_nombre", extra)}</div>
<h2>Mejores prospectos de la muestra</h2>
<div class="scroll"><table class="top"><thead><tr><th>Puntaje</th><th>Negocio</th><th>Rubro</th><th>Ciudad</th>
<th>Por qué</th><th>Gancho para el mail</th></tr></thead><tbody>{filas_top}</tbody></table></div>
</body></html>"""


def cmd_analizar():
    crudo = cargar_crudo()
    emails = leer_json(EMAILS, {})
    con_emails = bool(emails)
    negocios = construir_negocios(crudo, emails)
    rubros = resumir(negocios, ["rubro"], con_emails)
    ciudades = resumir(negocios, ["ciudad"], con_emails)
    cruce = resumir(negocios, ["rubro", "ciudad"], con_emails)

    carpeta = RESULTADOS / datetime.now().strftime("%Y-%m-%d_%H%M")
    carpeta.mkdir(parents=True, exist_ok=True)
    orden = sorted(negocios, key=lambda n: (-n["puntaje"], n["rubro"], n["ciudad"]))
    escribir_csv(carpeta / "negocios.csv", orden, COLUMNAS_NEGOCIOS)
    escribir_csv(carpeta / "rubros.csv", rubros)
    escribir_csv(carpeta / "ciudades.csv", ciudades)
    escribir_csv(carpeta / "rubro_ciudad.csv", cruce)
    (carpeta / "reporte.html").write_text(reporte_html(rubros, ciudades, negocios, con_emails), encoding="utf-8")

    print(f"\n{'Rubro':<32}{'Calif.':>8}{'Sin resp 90d':>14}{'Nunca resp':>12}{'Reseñas/mes':>13}{'Indep.':>8}")
    for r in rubros:
        print(f"{r['rubro_nombre']:<32}{fmt(r['pct_calificados'], '%'):>8}"
              f"{fmt(r['pct_sin_resp_reciente'], '%'):>14}{fmt(r['pct_nunca_responde'], '%'):>12}"
              f"{fmt(r['resenas_mes_mediana']):>13}{r['independientes']:>8}")
    print(f"\n{'Ciudad':<32}{'Calif.':>8}{'Sin resp 90d':>14}{'Nunca resp':>12}{'Reseñas/mes':>13}{'Indep.':>8}")
    for r in ciudades:
        print(f"{r['ciudad_nombre']:<32}{fmt(r['pct_calificados'], '%'):>8}"
              f"{fmt(r['pct_sin_resp_reciente'], '%'):>14}{fmt(r['pct_nunca_responde'], '%'):>12}"
              f"{fmt(r['resenas_mes_mediana']):>13}{r['independientes']:>8}")
    print(f"\nResultados en: {carpeta}")
    print("Abrí reporte.html para verlo, y mandame rubros.csv, ciudades.csv, rubro_ciudad.csv y negocios.csv.")
    return carpeta


# ---------------------------------------------------------------------------
def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        if cmd == "estimar":
            cmd_estimar(Apify(token()) if (os.environ.get("APIFY_TOKEN") or TOKEN.exists()) else None)
        elif cmd == "descargar":
            cmd_descargar()
        elif cmd == "emails":
            cmd_emails()
        elif cmd == "analizar":
            cmd_analizar()
        elif cmd == "todo":
            cmd_descargar()
            cmd_emails()
            cmd_analizar()
        else:
            print(__doc__)
    except ErrorApify as e:
        sys.exit(f"\nError de Apify: {e}")


if __name__ == "__main__":
    main()
