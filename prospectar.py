"""Modo prospección: arma la lista de negocios para contactar por mail.

Uso (desde esta carpeta):
    py prospectar.py estimar           cuántas zonas alcanza a revisar el crédito (todas las cuentas), sin gastar nada
    py prospectar.py buscar            revisa zonas que faltan con Apify, hasta donde alcance el crédito
    py prospectar.py buscar --max 10   como mucho 10 zonas
    py prospectar.py buscar --si       sin preguntar antes de arrancar (lo usa la nube)
    py prospectar.py lista             busca los mails y arma la lista de prospectos (gratis, se puede repetir)
    py prospectar.py migrar            pasa los datos viejos de datos/ a prospectos/prospeccion/ (una sola vez)

Los datos de la prospección viven en el repo privado (prospectos/prospeccion/, comprimidos), así la
búsqueda corre también en GitHub (Action "prospeccion"). Usa todas las cuentas de Apify en orden y deja
PROSP_RESERVA_USD sin tocar para las tandas. Después de cada zona sube el avance a GitHub.
La lista guarda solo las prioridades de PROSP_PRIORIDADES (hoy, solo A).
"""

import re
import subprocess
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import config as C
from analisis import construir_negocios, fecha, norm
from apify import Apify, Cuentas, ErrorApify
from estudio import (BASE, escribir_csv, guardar_json, leer_json, token, tokens)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

SALIDA = BASE / "prospectos"                 # el repo privado (radar-datos)
DIR = SALIDA / "prospeccion"
CRUDO_P = DIR / "crudo"                      # una zona por archivo, comprimido (.json.gz)
CRUDO = DIR / "estudio"                      # lo que se bajó en el estudio de nichos (también sirve)
ZONAS = DIR / "zonas.json"
EMAILS = DIR / "emails.json"
MX = DIR / "mx.json"
EXPORTADOS = DIR / "exportados.json"
VIEJO = BASE / "datos"                       # dónde estaba todo antes del 20/11/2026 (solo para migrar)

PALABRAS_ES = {"el", "la", "los", "las", "muy", "comida", "servicio", "excelente", "pero", "que",
               "con", "para", "una", "es", "lugar", "buena", "bueno", "todo", "gracias", "mal",
               "atención", "atencion", "rico", "deliciosa", "precio", "volver", "recomiendo"}


def slug(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def costo_lugar():
    p = C.PRECIOS
    return p["lugar"] + p["detalle"] + C.PROSP_RESENAS_POR_NEGOCIO * p["resena"]


def costo_zona():
    lugares = len(C.PROSP_RUBROS) * C.PROSP_NEGOCIOS_POR_BUSQUEDA
    return C.PRECIOS["inicio"] + lugares * costo_lugar()


def entrada_zona(ubicacion):
    return {
        "searchStringsArray": [C.RUBROS[r]["busqueda"] for r in C.PROSP_RUBROS],
        "locationQuery": ubicacion,
        "maxCrawledPlacesPerSearch": C.PROSP_NEGOCIOS_POR_BUSQUEDA,
        "language": "en",
        "maxReviews": C.PROSP_RESENAS_POR_NEGOCIO,
        "reviewsSort": "newest",
        "scrapeReviewsPersonalData": True,   # para saludar por el nombre en la respuesta de muestra
        "scrapePlaceDetailPage": False,
        "scrapeContacts": False,
        "maxImages": 0,
        "maxQuestions": 0,
    }


def zonas_en_orden():
    """Alterna ciudades: zona 1 de cada ciudad, después la 2, etc."""
    listas = [[(c, z) for z in zs] for c, zs in C.PROSP_ZONAS.items()]
    orden = []
    for i in range(max(len(x) for x in listas)):
        for lst in listas:
            if i < len(lst):
                orden.append(lst[i])
    return orden


def clave(ciudad, zona):
    return f"{ciudad}|{zona}"


def archivo_zona(ciudad, zona):
    return CRUDO_P / f"{ciudad}__{slug(zona)}.json.gz"


def zona_hecha(ciudad, zona, estado=None):
    """Hecha = se bajó con negocios. Si Google Maps no encontró la zona dos veces, se saltea."""
    estado = estado if estado is not None else leer_json(ZONAS, {})
    if estado.get(clave(ciudad, zona), {}).get("vacia", 0) >= 2:
        return True
    p = archivo_zona(ciudad, zona)
    return p.exists() and bool(leer_json(p, {}).get("items"))


def ubicacion_alternativa(zona):
    """Segundo intento si la zona vino vacía: 'Downtown, Atlanta, Georgia, USA' -> 'Downtown Atlanta, Georgia, USA'."""
    partes = [x.strip() for x in zona.split(",")]
    return f"{partes[0]} {partes[1]}, " + ", ".join(partes[2:]) if len(partes) >= 3 else zona


# ---------------------------------------------------------------------------
def cuentas_apify():
    return Cuentas(tokens(), fabrica=lambda t: Apify(t))


def tope_zona():
    return costo_zona() * 1.1


def zonas_que_alcanzan(cuentas):
    """Cuántas zonas se pueden pagar con las cuentas, dejando la reserva para las tandas.
    Cada zona tiene que entrar entera en una sola cuenta."""
    sobra = cuentas.libre_total() - C.PROSP_RESERVA_USD
    n = 0
    for c in cuentas.cuentas:
        libre = c["libre"] - C.PROSP_MARGEN_USD
        while libre >= tope_zona() and sobra >= tope_zona():
            libre -= tope_zona()
            sobra -= tope_zona()
            n += 1
    return n


def cmd_estimar(cuentas=None):
    estado = leer_json(ZONAS, {})
    todas = zonas_en_orden()
    hechas = [z for z in todas if zona_hecha(*z, estado)]
    pendientes = [z for z in todas if not zona_hecha(*z, estado)]
    cz = costo_zona()
    print(f"Rubros: {', '.join(C.RUBROS[r]['nombre'] for r in C.PROSP_RUBROS)}")
    print(f"Zonas: {len(todas)} en total | revisadas: {len(hechas)} | faltan: {len(pendientes)}")
    print(f"Cada zona: hasta {len(C.PROSP_RUBROS) * C.PROSP_NEGOCIOS_POR_BUSQUEDA} negocios "
          f"con {C.PROSP_RESENAS_POR_NEGOCIO} reseñas, como máximo USD {cz:.2f}")
    if cuentas is None:
        return pendientes, None, estado
    if not cuentas.cuentas:
        print("Ninguna cuenta de Apify responde: revisá los tokens.")
        return pendientes, None, estado
    print(f"Crédito de Apify: USD {cuentas.libre_total():.2f} libres en {len(cuentas.cuentas)} cuentas "
          f"(USD {C.PROSP_RESERVA_USD:.2f} quedan reservados para las tandas)")
    n = min(zonas_que_alcanzan(cuentas), len(pendientes))
    print(f"Alcanza para al menos {n} zonas (más si cada zona sale menos que el máximo)." if n else
          "No alcanza para ninguna zona: esperá a que se recargue el crédito o sumá otra cuenta.")
    return pendientes, n, estado


def cmd_buscar(confirmar=True, max_zonas=None):
    """Revisa zonas una tras otra hasta que se termine el crédito (dejando la reserva para las tandas),
    se llegue a max_zonas o no queden zonas. Usa todas las cuentas de Apify, en orden."""
    traer()
    cuentas = cuentas_apify()
    pendientes, n, estado = cmd_estimar(cuentas)
    if n is None:
        sys.exit("No se pudo leer el crédito de Apify. Probá de nuevo en un rato.")
    # Primero se retoman corridas que hayan quedado a medias.
    en_curso = [tuple(k.split("|", 1)) for k, v in estado.items()
                if v.get("run_id") and not zona_hecha(*k.split("|", 1), estado)]
    cola = en_curso + [z for z in pendientes if z not in en_curso]
    if max_zonas is not None:
        cola = cola[:max(0, max_zonas)]
    if not cola:
        print("No quedan zonas por revisar.")
        return 0
    if n == 0 and not en_curso:
        return 0
    print(f"\nVoy a revisar hasta {min(len(cola), n + len(en_curso))} zonas "
          f"(cada una cuesta entre USD 0,50 y {costo_zona():.2f}).")
    if confirmar and input("¿Arranco? (s/n) ").strip().lower() not in ("s", "si", "sí", "y"):
        sys.exit("Cancelado. No se gastó nada.")

    hechas_ahora = 0
    for ciudad, zona in cola:
        k = clave(ciudad, zona)
        previo_k = estado.get(k, {})
        retomar = bool(previo_k.get("run_id"))
        if retomar:
            cuenta = cuentas.por_id(previo_k.get("cuenta")) or (cuentas.cuentas[0] if cuentas.cuentas else None)
            if not cuenta:
                print(f"\n{zona}: no encuentro la cuenta con la que se arrancó. La salteo por ahora.")
                continue
        else:
            if cuentas.libre_total() - tope_zona() < C.PROSP_RESERVA_USD:
                print(f"\nSe llegó a la reserva para las tandas (quedan USD {cuentas.libre_total():.2f}): freno acá.")
                break
            cuenta = cuentas.para(tope_zona() + C.PROSP_MARGEN_USD)
            if not cuenta:
                print("\nNinguna cuenta tiene crédito para otra zona entera: freno acá.")
                break
        api = cuenta["api"]
        intentos = previo_k.get("vacia", 1 if previo_k.get("negocios") == 0 else 0)
        entrada = entrada_zona(zona if intentos == 0 else ubicacion_alternativa(zona))
        if retomar:
            run_id = previo_k["run_id"]
            print(f"\n{zona}: retomo la corrida que quedó a medias...")
        else:
            print(f"\n{zona}: arrancando (cuenta {cuenta['n']})...")
            try:
                run_id = api.arrancar(C.ACTOR_MAPS, entrada, tope_zona())["id"]
            except ErrorApify as e:
                print(f"  Apify no dejó arrancar la zona ({e}). Freno acá.")
                break
            estado[k] = {"run_id": run_id, "cuenta": cuenta["id"]}
            guardar_json(ZONAS, estado)
            subir(f"Prospección: arranca {zona}")
        inicio, aviso = time.time(), [0.0]

        def avanzar(_r):
            m = (time.time() - inicio) / 60
            if m - aviso[0] >= 1:
                aviso[0] = m
                print(f"  {zona}: corriendo ({m:.0f} min)...")

        try:
            run = api.esperar(run_id, avanzar)
        except KeyboardInterrupt:
            sys.exit("\nCortado. La corrida sigue en Apify: volvé a correr 'py prospectar.py buscar' y la retoma.")
        items = api.items(run["defaultDatasetId"])
        if not items:
            estado[k] = {"vacia": intentos + 1}
            guardar_json(ZONAS, estado)
            subir(f"Prospección: {zona} vino vacía")
            print(f"  {zona}: Google Maps no devolvió negocios. "
                  + ("La próxima vez pruebo escribiéndola distinto." if intentos == 0 else "La salteo."))
            continue
        guardar_json(archivo_zona(ciudad, zona), {
            "ciudad": ciudad, "zona": zona,
            "fecha": run.get("finishedAt") or datetime.now(timezone.utc).isoformat(),
            "run_id": run_id, "estado_corrida": run["status"],
            "completa": run["status"] == "SUCCEEDED", "entrada": entrada, "items": items,
        })
        estado[k] = {"hecha": True, "negocios": len(items), "costo": run.get("usageTotalUsd")}
        guardar_json(ZONAS, estado)
        hechas_ahora += 1
        print(f"  {zona}: {len(items)} negocios ({run['status']}), "
              f"USD {float(run.get('usageTotalUsd') or 0):.2f}. Crédito libre: USD {cuentas.libre_total():.2f}")
        subir(f"Prospección: {zona} ({len(items)} negocios)")
    print(f"\nListo: {hechas_ahora} zonas nuevas en esta corrida. Seguí con: py prospectar.py lista")
    return hechas_ahora


# ---------------------------------------------------------------------------
# Sincronización con el repo privado (para que la nube y las dos PC vean lo mismo)
# ---------------------------------------------------------------------------
def _git(*args):
    return subprocess.run(["git", *args], cwd=SALIDA, capture_output=True, text=True)


def _usa_git():
    return (SALIDA / ".git").exists() and bool(_git("remote").stdout.strip())


def traer():
    if _usa_git() and _git("pull", "--rebase").returncode != 0:
        sys.exit("No se pudo traer lo último de GitHub (git pull falló en prospectos/). Resolvelo antes de seguir.")


def subir(mensaje):
    """Sube el avance de la prospección. Si mientras tanto el envío automático subió algo, lo trae y reintenta."""
    if not _usa_git():
        return True
    rutas = [x for x in ("prospeccion", "prospectos_todos.csv") if (SALIDA / x).exists()]
    rutas += [p.name for p in SALIDA.glob("prospectos_nuevos_*.csv")]
    if not rutas:
        return True
    _git("add", "-A", "--", *rutas)
    if _git("diff", "--cached", "--quiet").returncode == 0:
        return True
    _git("commit", "-m", mensaje)
    for _ in range(5):
        if _git("push").returncode == 0:
            return True
        _git("pull", "--rebase")
    print("  OJO: no se pudo subir el avance a GitHub (se reintenta con la próxima zona).")
    return False


# ---------------------------------------------------------------------------
# Lista de prospectos
# ---------------------------------------------------------------------------
def cargar_bloques():
    bloques = []
    for ciudad in C.PROSP_ZONAS:
        p = CRUDO / f"{ciudad}.json.gz"        # lo que ya se bajó en el estudio, sin costo extra
        if p.exists():
            b = leer_json(p, {})
            b["zona"] = "estudio"
            bloques.append((ciudad, b))
    for p in sorted(CRUDO_P.glob("*.json.gz")):
        b = leer_json(p, {})
        if b.get("ciudad") in C.PROSP_ZONAS:
            bloques.append((b["ciudad"], b))
    return bloques


def cmd_migrar():
    """Pasa los datos de la prospección de datos/ (solo en la PC) a prospectos/prospeccion/ (en GitHub,
    comprimidos). No borra nada de datos/. Se puede repetir: no pisa lo que ya está migrado."""
    pares = [(p, CRUDO_P / (p.stem + ".json.gz")) for p in sorted((VIEJO / "prospeccion" / "crudo").glob("*.json"))]
    pares += [(p, CRUDO / (p.stem + ".json.gz")) for p in sorted((VIEJO / "crudo").glob("*.json"))]
    pares += [(VIEJO / "prospeccion" / "zonas.json", ZONAS), (VIEJO / "prospeccion" / "exportados.json", EXPORTADOS),
              (VIEJO / "emails.json", EMAILS), (VIEJO / "mx.json", MX)]
    hechos = 0
    for origen, destino in pares:
        if not origen.exists() or destino.exists():
            continue
        datos = leer_json(origen, None)
        if datos is None:
            print(f"  No pude leer {origen.name}: lo salteo.")
            continue
        guardar_json(destino, datos)
        hechos += 1
    print(f"Migrados {hechos} archivos a {DIR}.")
    if hechos:
        subir("Prospección: datos migrados desde la PC")
    return hechos


def es_espanol(texto):
    palabras = re.findall(r"[a-záéíóúñü]+", (texto or "").lower())
    return sum(1 for w in palabras if w in PALABRAS_ES) >= 3


def dudoso(texto):
    """1-2 estrellas con texto positivo y sin nada negativo: el cliente se equivocó al puntuar."""
    t = (texto or "").lower()
    return any(p in t for p in C.PALABRAS_POSITIVAS) and not any(p in t for p in C.PALABRAS_NEGATIVAS)


def gancho(lugar, ahora):
    """La reseña para la muestra gratis: la negativa sin responder más nueva; si no hay
    (o parece un error de puntaje), la sin responder más nueva que tenga texto."""
    rs = []
    for r in lugar.get("reviews") or []:
        if str(r.get("reviewOrigin") or "Google").lower() != "google":
            continue
        d = fecha(r.get("publishedAtDate"))
        if not d or str(r.get("responseFromOwnerText") or "").strip():
            continue
        rs.append((d, r))
    rs.sort(key=lambda x: x[0], reverse=True)
    neg = [(d, r) for d, r in rs if (r.get("stars") or 5) <= 2
           and (ahora - d).days <= C.DIAS_NEGATIVA and not dudoso(r.get("text"))]
    con_texto = [(d, r) for d, r in rs if str(r.get("text") or "").strip()
                 and not ((r.get("stars") or 5) <= 2 and dudoso(r.get("text")))]
    elegido = neg[0] if neg else (con_texto[0] if con_texto else (rs[0] if rs else None))
    if not elegido:
        return {}
    # Segunda reseña para el mail: de preferencia una positiva con texto (muestra que sabés
    # responder las dos), si no cualquier otra sin responder.
    resto = [x for x in rs if x[1] is not elegido[1]]
    positivas = [x for x in resto if (x[1].get("stars") or 0) >= 4 and str(x[1].get("text") or "").strip()]
    otras = [x for x in resto if str(x[1].get("text") or "").strip()]
    segundo = positivas[0] if positivas else (otras[0] if otras else (resto[0] if resto else None))

    def datos(par, prefijo):
        if not par:
            return {f"{prefijo}_{k}": "" for k in ("estrellas", "fecha", "autor", "texto")}
        d, r = par
        return {
            f"{prefijo}_estrellas": r.get("stars"),
            f"{prefijo}_fecha": d.date().isoformat(),
            f"{prefijo}_autor": str(r.get("name") or "").strip().split(" ")[0] if r.get("name") else "",
            f"{prefijo}_texto": limpiar(r.get("text"))[:1000],
        }

    out = {"gancho_tipo": "negativa" if neg else "sin responder",
           "gancho_link": elegido[1].get("reviewUrl") or "",
           "sin_responder_muestra": len(rs)}
    out.update(datos(elegido, "gancho"))
    out.update(datos(segundo, "gancho2"))
    return out


def limpiar(texto):
    """Saca restos de HTML del texto de la reseña."""
    t = re.sub(r"<br\s*/?>", "\n", str(texto or ""), flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def relacionado(email, nombre, web):
    """¿Un mail de otro dominio tiene que ver con el negocio? Comparte alguna palabra
    del nombre o de la web. Si no, puede ser del diseñador web o del dueño del edificio."""
    dom = re.sub(r"[^a-z0-9]", "", email.split("@")[1].rsplit(".", 1)[0].lower())
    palabras = set(re.findall(r"[a-z0-9]{3,}", norm(nombre)))
    host = (re.sub(r"^https?://(www\.)?", "", str(web or "").lower()).split("/")[0]).rsplit(".", 1)[0]
    palabras |= set(re.findall(r"[a-z0-9]{4,}", host))
    genericas = {"the", "and", "inc", "llc", "restaurant", "bar", "grill", "nail", "nails", "spa",
                 "moving", "movers", "property", "management", "realty", "group", "services", "salon",
                 "kitchen", "cafe", "best", "home", "homes", "city", "usa", "company", "studio",
                 # ciudades: "atlantawebdesign.com" no tiene que ver con un negocio de Atlanta
                 "atlanta", "houston", "los", "angeles", "kansas", "texas", "georgia", "california"}
    return any(p in dom for p in palabras - genericas) or any(p in host for p in [dom] if len(dom) >= 4)


def tipo_email(email, dominio):
    if not email:
        return ""
    from emails import GRATUITOS
    dom = email.split("@")[1]
    if dominio and (dom == dominio or dom.endswith("." + dominio)):
        return "propio"
    return "gratuito" if dom in GRATUITOS else "otro dominio"


COLUMNAS = [
    "prioridad", "puntaje", "rubro_nombre", "ciudad_nombre", "zona", "nombre", "email", "email_tipo",
    "gancho_tipo", "gancho_estrellas", "gancho_fecha", "gancho_autor", "gancho_texto", "gancho_link",
    "gancho2_estrellas", "gancho2_fecha", "gancho2_autor", "gancho2_texto",
    "sin_responder_muestra", "porque", "sin_resp_reciente", "n_muestra", "tasa_respuesta", "negativa_sin_resp", "en_espanol",
    "rating", "resenas_totales", "resenas_por_mes", "web", "telefono", "direccion", "maps",
    "detectado", "place_id",
]


def cmd_lista():
    from emails import buscar_todos, chequear_mx

    bloques = cargar_bloques()
    if not bloques:
        sys.exit("No hay datos. Corré primero: py prospectar.py buscar")
    negocios = construir_negocios(bloques, con_lugar=True)
    # Un negocio puede aparecer en varias búsquedas: queda el primero (cada fila es rubro + negocio).
    # A y B: señal reciente y tamaño razonable. C: el resto con alguna reseña sin responder
    # (señal más vieja, negocio muy chico o muy grande, o mail de otro dominio).
    cand = []
    for n in negocios:
        if n["rubro"] not in C.PROSP_RUBROS or not (n["independiente"] and n["reclamado"]):
            continue
        senal = n["sin_resp_reciente"] >= 1 or n["negativa_sin_resp"]
        if not (senal or n["sin_resp_total"] >= 1):
            continue
        en_rango = C.PROSP_MIN_RESENAS_TOTALES <= n["resenas_totales"] <= C.PROSP_MAX_RESENAS_TOTALES
        n["_c"] = not (senal and en_rango)
        cand.append(n)
    print(f"Negocios revisados: {len(negocios)} | con alguna reseña sin responder: {len(cand)}")

    # Mails: se buscan solo en las webs de los candidatos que no se revisaron antes.
    webs = {n["dominio"]: n["web"] for n in cand if n["tipo_web"] == "propia" and n["dominio"]}
    previos = leer_json(EMAILS, {})
    faltan = [d for d in webs if d not in previos
              or (previos[d].get("estado") != "ok" and not previos[d].get("reintento"))]
    if faltan:
        print(f"Buscando mails en {len(faltan)} webs...")

        def avanzar(i, total):
            if i % 25 == 0 or i == total:
                print(f"  {i}/{total}")
        previos = buscar_todos(webs, previos, avanzar)
        guardar_json(EMAILS, previos)

    from emails import elegir
    for n in cand:
        r = previos.get(n["dominio"]) if n["dominio"] else None
        # Se suma el mejor que se eligió al buscar: la lista guardada se corta en 10 mails.
        todos = list((r or {}).get("emails") or []) + ([r["email"]] if r and r.get("email") else [])
        n["email"] = elegir(todos, n["dominio"])
    con_mail = [n for n in cand if n["email"]]
    for n in con_mail:
        if tipo_email(n["email"], n["dominio"]) == "otro dominio" and not relacionado(n["email"], n["nombre"], n["web"]):
            n["_c"] = True

    mx = chequear_mx({n["email"].split("@")[1] for n in con_mail}, leer_json(MX, {}))
    guardar_json(MX, mx)
    validos = [n for n in con_mail if mx.get(n["email"].split("@")[1]) is not False]
    print(f"Con mail: {len(con_mail)} | con mail que puede recibir: {len(validos)}")

    # Un mail por negocio, aunque aparezca en dos rubros o zonas.
    vistos, filas = set(), []
    hoy = datetime.now().strftime("%Y-%m-%d")
    exportados = leer_json(EXPORTADOS, {})
    for n in sorted(validos, key=lambda n: (-int(n["prospecto_calificado"]), -n["puntaje"])):
        e = n["email"].lower()
        if e in vistos:
            continue
        vistos.add(e)
        lugar = n.pop("_lugar")
        textos = " ".join(str(r.get("text") or "") for r in (lugar.get("reviews") or []))
        n.update(gancho(lugar, n.pop("_ahora")))
        n.update({
            "prioridad": "C" if n.pop("_c") else (
                "A" if n["prospecto_calificado"] and (n["tasa_respuesta"] is None
                                                      or n["tasa_respuesta"] < C.PROSP_TASA_MAX_A) else "B"),
            "email_tipo": tipo_email(e, n["dominio"]),
            "en_espanol": es_espanol(textos),
            "zona": "" if n["zona"] == "estudio" else n["zona"].split(",")[0],
            "detectado": exportados.get(e, hoy),
        })
        filas.append(n)

    filas.sort(key=lambda f: (f["prioridad"], -f["puntaje"], -f["sin_resp_reciente"]))
    todas = filas
    # Solo quedan las prioridades elegidas (hoy, solo A). Los B que se sumen tienen que tener
    # una reseña negativa sin responder: es el mejor gancho.
    filas = [f for f in filas if f["prioridad"] in C.PROSP_PRIORIDADES
             and (f["prioridad"] != "B" or f.get("negativa_sin_resp") in (True, "si"))]
    nuevos = [f for f in filas if f["email"].lower() not in exportados]
    for f in nuevos:
        exportados[f["email"].lower()] = hoy
    guardar_json(EXPORTADOS, exportados)

    SALIDA.mkdir(exist_ok=True)
    escribir_csv(SALIDA / "prospectos_todos.csv", filas, COLUMNAS)
    if nuevos:
        escribir_csv(SALIDA / f"prospectos_nuevos_{hoy}.csv", nuevos, COLUMNAS)

    print(f"\n{'Rubro':<32}{'A':>5}{'B':>5}{'C':>5}{'En lista':>10}")
    for r in C.PROSP_RUBROS:
        cuenta = [sum(1 for f in todas if f["rubro"] == r and f["prioridad"] == x) for x in "ABC"]
        quedan = sum(1 for f in filas if f["rubro"] == r)
        print(f"{C.RUBROS[r]['nombre']:<32}" + "".join(f"{c:>5}" for c in cuenta) + f"{quedan:>10}")
    print(f"\nEn la lista quedan solo: {', '.join(C.PROSP_PRIORIDADES)}"
          f"{' (B solo con negativa sin responder)' if 'B' in C.PROSP_PRIORIDADES else ''}")
    print(f"Total: {len(filas)} prospectos | nuevos en esta lista: {len(nuevos)}")
    print(f"Archivos en: {SALIDA}")
    subir(f"Prospección: lista rearmada ({len(filas)} prospectos, {len(nuevos)} nuevos)")
    return filas, nuevos


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else ""
    try:
        if cmd == "estimar":
            cmd_estimar(cuentas_apify())
        elif cmd == "buscar":
            maximo = None
            if "--max" in args:
                try:
                    maximo = int(args[args.index("--max") + 1])
                except (IndexError, ValueError):
                    sys.exit("Uso: py prospectar.py buscar --max 10")
            cmd_buscar(confirmar="--si" not in args, max_zonas=maximo)
        elif cmd == "lista":
            traer()
            cmd_lista()
        elif cmd == "migrar":
            cmd_migrar()
        else:
            print(__doc__)
    except ErrorApify as e:
        sys.exit(f"\nError de Apify: {e}")


if __name__ == "__main__":
    main()
