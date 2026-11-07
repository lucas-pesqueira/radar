"""Campaña de mails: arma la tanda del día y lleva el registro de cada prospecto.

Uso (desde esta carpeta):
    py campana.py tanda              arma la tanda de hoy (verifica las reseñas en vivo con Apify)
    py campana.py tanda --prueba     igual, pero sin Apify y sin guardar nada (para probar)
    py campana.py respondio MAIL     el negocio respondió: no recibe más seguimientos
    py campana.py baja MAIL          pidió no recibir más mails: no se le escribe nunca más
    py campana.py estado             resumen de la campaña

La tanda queda en prospectos/campana/tandas/tanda_<fecha>.json. Con ese archivo Claude
escribe los mails y los deja como borradores en la casilla de envío.
"""

import csv
import os
import re
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone

import config as C
from analisis import fecha
from apify import Apify, ErrorApify
from estudio import BASE, guardar_json, leer_json, token
from prospectar import es_espanol, gancho

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

DATOS = BASE / "prospectos"        # repo privado aparte (radar-datos): se sincroniza entre PC
DIR = DATOS / "campana"
REGISTRO = DIR / "registro.json"
BAJAS = DIR / "bajas.json"
TANDAS = DIR / "tandas"
PROSPECTOS = BASE / "prospectos" / "prospectos_todos.csv"
ORDEN_PRIORIDAD = {"A": 0, "B": 1, "C": 2}


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def dias_habiles(desde, hasta):
    """Días hábiles (lunes a viernes) entre dos fechas, sin contar la primera."""
    n, d = 0, desde
    while d < hasta:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def hoy():
    """Fecha de trabajo. Con RADAR_FECHA=AAAA-MM-DD se registra esa fecha (para preparar el envío de otro día)."""
    f = os.environ.get("RADAR_FECHA")
    return date.fromisoformat(f) if f else date.today()


def nombre_prolijo(nombre):
    """'NAIL TALK & SPA (GEORGIA TECH)' -> 'Nail Talk & Spa'. 'BZH Properties Inc.' -> 'BZH Properties'."""
    s = str(nombre or "").strip()
    s = re.sub(r"\s*[\(\[].*?[\)\]]", "", s)                       # aclaraciones entre paréntesis
    s = re.split(r"\s+[-–—|]\s+", s)[0]                             # "Negocio - Zona" / "Negocio | Algo"
    s = re.sub(r",?\s+(inc|llc|l\.l\.c|co|corp|ltd)\.?$", "", s, flags=re.I)
    letras = re.sub(r"[^A-Za-z]", "", s)
    if len(letras) > 4 and letras.isupper():                        # todo en mayúsculas
        s = " ".join(w if re.search(r"\d", w) or (len(w) <= 3 and w.isalpha() and len(w) > 1
                                                   and not re.search(r"[AEIOU]", w))
                     else w.capitalize() for w in s.split())
    return re.sub(r"\s+", " ", s).strip(" ,.-")


def cargar_prospectos():
    if not PROSPECTOS.exists():
        sys.exit("No hay lista de prospectos. Corré primero: py prospectar.py lista")
    with PROSPECTOS.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def lugares_guardados():
    """Último dato crudo de cada negocio (del estudio y de la prospección), por placeId."""
    out = {}
    archivos = sorted((BASE / "datos" / "crudo").glob("*.json")) + \
        sorted((BASE / "datos" / "prospeccion" / "crudo").glob("*.json"))
    for p in archivos:
        b = leer_json(p, {})
        for l in b.get("items", []):
            if l.get("placeId"):
                out[l["placeId"]] = (l, fecha(b.get("fecha")) or datetime.now(timezone.utc))
    return out


# ---------------------------------------------------------------------------
# Verificación en vivo
# ---------------------------------------------------------------------------
def costo_verificacion(n):
    p = C.PRECIOS
    return p["inicio"] + n * (p["lugar"] + p["detalle"] + C.VERIFICAR_RESENAS * p["resena"])


def verificar(api, place_ids):
    """Vuelve a bajar las reseñas más nuevas de estos negocios. Devuelve {placeId: lugar}."""
    entrada = {
        "placeIds": place_ids,
        "language": "en",
        "maxReviews": C.VERIFICAR_RESENAS,
        "reviewsSort": "newest",
        "scrapeReviewsPersonalData": True,
        "scrapePlaceDetailPage": False,
        "scrapeContacts": False,
        "maxImages": 0,
        "maxQuestions": 0,
    }
    run = api.arrancar(C.ACTOR_MAPS, entrada, max(0.5, costo_verificacion(len(place_ids)) * 1.2 + 0.01))  # Apify exige un tope mínimo de USD 0,50
    inicio = time.time()

    def avanzar(_r):
        print(f"  verificando reseñas ({(time.time() - inicio) / 60:.0f} min)...")

    run = api.esperar(run["id"], avanzar, cada=20)
    items = api.items(run["defaultDatasetId"])
    return {l.get("placeId"): l for l in items if l.get("placeId")}


# ---------------------------------------------------------------------------
# Tanda
# ---------------------------------------------------------------------------
def seguimientos_pendientes(registro):
    """Prospectos a los que hoy les toca un seguimiento."""
    out, d = [], hoy()
    for email, r in registro.items():
        if r.get("estado") not in ("enviado", "seguimiento 1"):
            continue
        primero = date.fromisoformat(r["fechas"]["enviado"])
        transcurridos = dias_habiles(primero, d)
        if r["estado"] == "enviado" and transcurridos >= C.SEGUIMIENTO_DIAS[0]:
            out.append((email, 1))
        elif r["estado"] == "seguimiento 1" and transcurridos >= C.SEGUIMIENTO_DIAS[1]:
            out.append((email, 2))
    out.sort(key=lambda x: registro[x[0]]["fechas"]["enviado"])
    return out


def cmd_tanda(prueba=False, limite=None):
    limite = limite or C.ENVIOS_POR_DIA
    registro = leer_json(REGISTRO, {})
    bajas = set(leer_json(BAJAS, []))
    d = hoy().isoformat()
    ya_hoy = [e for e, r in registro.items() if d in r.get("fechas", {}).values()]
    if ya_hoy and not prueba:
        sys.exit(f"Ya se armó una tanda hoy ({len(ya_hoy)} mails). La próxima, mañana.")

    # 1) Seguimientos primero: son los que ya están en conversación.
    segs = [(e, n) for e, n in seguimientos_pendientes(registro) if e not in bajas][:limite]
    items = []
    for email, n in segs:
        r = registro[email]
        items.append({"tipo": f"seguimiento {n}", "email": email, "negocio": r["negocio"],
                      "rubro": r["rubro"], "precio": r["precio"], "ciudad": r["ciudad"],
                      "asunto": r["asunto"], "enviado": r["fechas"]["enviado"]})

    # 2) Prospectos nuevos para completar el cupo.
    cupo = limite - len(items)
    nuevos, salteados = [], []
    if cupo > 0:
        contactados = set(registro) | bajas
        cand = [p for p in cargar_prospectos() if p["email"].lower() not in contactados]
        cand = intercalar_rubros(cand)
        # Se verifican algunos de más por si alguno ya respondió sus reseñas.
        a_verificar = cand[:cupo + max(3, cupo // 4)]
        guardados = lugares_guardados()
        frescos = {}
        if a_verificar and not prueba:
            ids = [p["place_id"] for p in a_verificar if re.match(r"^(ChIJ|GhIJ)", p["place_id"])]
            api = Apify(token())
            usado, maximo = api.credito()
            costo = costo_verificacion(len(ids))
            if usado is not None and maximo and maximo - usado < costo:
                sys.exit(f"No alcanza el crédito de Apify para verificar (hace falta USD {costo:.2f}).")
            print(f"Verificando {len(ids)} negocios en Google Maps (como máximo USD {costo:.2f})...")
            frescos = verificar(api, ids)
        ahora = datetime.now(timezone.utc)
        for p in a_verificar:
            if len(nuevos) >= cupo:
                break
            pid = p["place_id"]
            if pid in frescos:
                lugar, cuando, verificado = frescos[pid], ahora, True
            elif pid in guardados:
                lugar, cuando = guardados[pid]
                verificado = False
            else:
                salteados.append((p["nombre"], "sin datos del negocio"))
                continue
            if lugar.get("permanentlyClosed") or lugar.get("temporarilyClosed"):
                salteados.append((p["nombre"], "cerrado"))
                continue
            g = gancho(lugar, cuando)
            if not g:
                salteados.append((p["nombre"], "ya respondió sus reseñas"))
                continue
            muestra = len([r for r in (lugar.get("reviews") or [])
                           if str(r.get("reviewOrigin") or "Google").lower() == "google"])
            textos = " ".join(str(r.get("text") or "") for r in (lugar.get("reviews") or []))
            resenas = [{"autor": nombre_autor(g["gancho_autor"]), "estrellas": g["gancho_estrellas"],
                        "fecha": g["gancho_fecha"], "texto": g["gancho_texto"]}]
            if g.get("gancho2_fecha"):
                resenas.append({"autor": nombre_autor(g["gancho2_autor"]), "estrellas": g["gancho2_estrellas"],
                                "fecha": g["gancho2_fecha"], "texto": g["gancho2_texto"]})
            nuevos.append({
                "tipo": "primer mail", "email": p["email"], "negocio": nombre_prolijo(p["nombre"]),
                "negocio_original": p["nombre"], "rubro": p["rubro_nombre"],
                "precio": C.PRECIO_RUBRO.get(rubro_clave(p["rubro_nombre"])),
                "ciudad": p["ciudad_nombre"], "prioridad": p["prioridad"],
                "sin_responder": g["sin_responder_muestra"], "de_las_ultimas": muestra,
                "resenas": resenas, "en_espanol": es_espanol(textos), "verificado": verificado,
                "place_id": pid, "maps": p.get("maps", ""),
            })
    items += nuevos

    tanda = {"fecha": d, "prueba": prueba, "items": items,
             "salteados": [{"negocio": n, "motivo": m} for n, m in salteados]}
    TANDAS.mkdir(parents=True, exist_ok=True)
    archivo = TANDAS / f"tanda_{d}{'_prueba' if prueba else ''}.json"
    guardar_json(archivo, tanda)

    if not prueba:
        for it in nuevos:
            registro[it["email"].lower()] = {
                "negocio": it["negocio"], "rubro": it["rubro"], "precio": it["precio"],
                "ciudad": it["ciudad"], "place_id": it["place_id"],
                "asunto": f"{it['negocio']}'s Google reviews",
                "estado": "enviado", "fechas": {"enviado": d},
            }
        for email, n in segs:
            registro[email]["estado"] = f"seguimiento {n}"
            registro[email]["fechas"][f"seguimiento {n}"] = d
        guardar_json(REGISTRO, registro)

    print(f"\nTanda de {d}{' (prueba)' if prueba else ''}: {len(nuevos)} primeros mails + {len(segs)} seguimientos")
    for n, m in salteados:
        print(f"  salteado: {n} ({m})")
    print(f"Archivo: {archivo}")
    print("Avisale a Claude que la tanda está lista para escribir los mails.")
    return tanda


def intercalar_rubros(cand):
    """Ordena por prioridad y puntaje dentro de cada rubro, y alterna rubros: así cada tanda
    prueba los 4 rubros por igual y se puede comparar cuál responde más."""
    por_rubro = {}
    for p in cand:
        por_rubro.setdefault(p["rubro_nombre"], []).append(p)
    for lst in por_rubro.values():
        lst.sort(key=lambda p: (ORDEN_PRIORIDAD.get(p["prioridad"], 9), -int(p["puntaje"] or 0)))
    out, i = [], 0
    while any(i < len(l) for l in por_rubro.values()):
        ronda = [l[i] for l in por_rubro.values() if i < len(l)]
        ronda.sort(key=lambda p: ORDEN_PRIORIDAD.get(p["prioridad"], 9))
        out += ronda
        i += 1
    return out


def nombre_autor(n):
    """Nombre de pila presentable, o vacío si no parece un nombre (apodos, símbolos)."""
    n = str(n or "").strip()
    if not re.fullmatch(r"[A-Za-zÀ-ÿ'’-]{2,20}", n):
        return ""
    return n[0].upper() + n[1:] if n.islower() else n


def rubro_clave(nombre):
    for k, r in C.RUBROS.items():
        if r["nombre"] == nombre:
            return k
    return None


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------
def cmd_marcar(email, estado):
    email = email.strip().lower()
    registro = leer_json(REGISTRO, {})
    if estado == "baja":
        bajas = leer_json(BAJAS, [])
        if email not in bajas:
            bajas.append(email)
            guardar_json(BAJAS, bajas)
    if email in registro:
        registro[email]["estado"] = estado
        registro[email]["fechas"][estado] = hoy().isoformat()
        guardar_json(REGISTRO, registro)
    elif estado != "baja":
        sys.exit(f"{email} no está en el registro.")
    print(f"{email}: {estado}.")


def cmd_estado():
    registro = leer_json(REGISTRO, {})
    bajas = leer_json(BAJAS, [])
    cuenta = {}
    for r in registro.values():
        cuenta[r["estado"]] = cuenta.get(r["estado"], 0) + 1
    total = len(cargar_prospectos()) if PROSPECTOS.exists() else 0
    print(f"Prospectos en la lista: {total} | contactados: {len(registro)} | bajas: {len(bajas)}")
    for e, n in sorted(cuenta.items()):
        print(f"  {e}: {n}")
    resp = cuenta.get("respondió", 0)
    if registro:
        print(f"Tasa de respuesta: {100 * resp / len(registro):.1f}%")


# ---------------------------------------------------------------------------
# Sincronización del registro entre PC (vía Git)
# ---------------------------------------------------------------------------
def _git(*args):
    return subprocess.run(["git", *args], cwd=DATOS, capture_output=True, text=True)


def _usa_git():
    """True si prospectos/ es un repo (el privado) con un remoto configurado. Si no, no se sincroniza nada."""
    if not (DATOS / ".git").exists():
        return False
    try:
        return bool(_git("remote").stdout.strip())
    except FileNotFoundError:
        sys.exit("No encuentro git. Instalalo: sin eso el registro puede quedar desactualizado entre PC.")


def sync_antes():
    """Trae el registro de la otra PC antes de leerlo. Si no puede, corta: no se trabaja con un registro viejo."""
    if not _usa_git():
        return
    r = _git("pull", "--ff-only")
    if r.returncode != 0:
        sys.exit("No se pudo traer el registro de la otra PC (git pull falló):\n"
                 + (r.stderr or r.stdout).strip()
                 + "\nResolvelo antes de seguir: si no, se puede escribir dos veces a un prospecto "
                   "o a alguien que pidió la baja.")
    print("Registro al día con GitHub.")


def sync_despues(mensaje):
    """Sube el registro para que la otra PC lo vea. Si falla, lo avisa fuerte."""
    if not _usa_git() or not DIR.exists():
        return
    _git("add", "-A")
    if _git("diff", "--cached", "--quiet").returncode == 0:
        return
    c = _git("commit", "-m", mensaje)
    p = _git("push") if c.returncode == 0 else c
    if p.returncode != 0:
        print("\n!!! ATENCIÓN: el registro NO se subió a GitHub. No uses la otra PC hasta resolverlo.\n"
              + (p.stderr or p.stdout).strip() + "\nProbá a mano: git push")
    else:
        print("Registro subido a GitHub.")


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else ""
    try:
        if cmd == "tanda":
            sync_antes()
            cmd_tanda(prueba="--prueba" in args)
            if "--prueba" not in args:
                sync_despues(f"Tanda {hoy().isoformat()}")
        elif cmd in ("respondio", "respondió") and len(args) > 1:
            sync_antes()
            cmd_marcar(args[1], "respondió")
            sync_despues(f"Respondió {args[1]}")
        elif cmd == "baja" and len(args) > 1:
            sync_antes()
            cmd_marcar(args[1], "baja")
            sync_despues(f"Baja {args[1]}")
        elif cmd == "estado":
            sync_antes()
            cmd_estado()
        else:
            print(__doc__)
    except ErrorApify as e:
        sys.exit(f"\nError de Apify: {e}")


if __name__ == "__main__":
    main()
