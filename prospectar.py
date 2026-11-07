"""Modo prospección: arma la lista de negocios para contactar por mail.

Uso (desde esta carpeta):
    py prospectar.py estimar   cuántas zonas alcanza a revisar tu crédito, sin gastar nada
    py prospectar.py buscar    revisa las zonas que faltan con Apify, hasta donde alcance el crédito
    py prospectar.py lista     busca los mails y arma la lista de prospectos (gratis, se puede repetir)

Se puede correr todos los meses: cada vez sigue con las zonas que faltan y la lista
nueva trae solo los prospectos que no estaban en las anteriores.
"""

import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import config as C
from analisis import construir_negocios, fecha, norm
from apify import Apify, ErrorApify
from estudio import (BASE, CRUDO, EMAILS, escribir_csv, guardar_json, leer_json, token)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

DIR = BASE / "datos" / "prospeccion"
CRUDO_P = DIR / "crudo"
ZONAS = DIR / "zonas.json"
MX = BASE / "datos" / "mx.json"
EXPORTADOS = DIR / "exportados.json"
SALIDA = BASE / "prospectos"

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
    return CRUDO_P / f"{ciudad}__{slug(zona)}.json"


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
def cmd_estimar(api=None):
    estado = leer_json(ZONAS, {})
    todas = zonas_en_orden()
    hechas = [z for z in todas if zona_hecha(*z, estado)]
    pendientes = [z for z in todas if not zona_hecha(*z, estado)]
    cz = costo_zona()
    print(f"Rubros: {', '.join(C.RUBROS[r]['nombre'] for r in C.PROSP_RUBROS)}")
    print(f"Zonas: {len(todas)} en total | revisadas: {len(hechas)} | faltan: {len(pendientes)}")
    print(f"Cada zona: hasta {len(C.PROSP_RUBROS) * C.PROSP_NEGOCIOS_POR_BUSQUEDA} negocios "
          f"con {C.PROSP_RESENAS_POR_NEGOCIO} reseñas, como máximo USD {cz:.2f}")
    libre = None
    if api:
        usado, maximo = api.credito()
        if usado is not None and maximo:
            libre = maximo - usado
            print(f"Crédito de Apify este mes: usaste USD {usado:.2f} de {maximo:.2f} (quedan {libre:.2f})")
    if libre is not None:
        n = int(max(0.0, libre - C.PROSP_MARGEN_USD) // cz)
        n = min(n, len(pendientes))
        print(f"Te alcanza para al menos {n} zonas (más si cada zona sale menos que el máximo)." if n else
              "No alcanza para ninguna zona: esperá a que se recargue el crédito de Apify.")
        return pendientes, n, estado
    return pendientes, None, estado


def cmd_buscar(confirmar=True):
    """Revisa zonas una tras otra hasta que se termine el crédito o no queden zonas."""
    api = Apify(token())
    pendientes, n, estado = cmd_estimar(api)
    if n is None:
        sys.exit("No se pudo leer tu crédito de Apify. Probá de nuevo en un rato.")
    # Primero se retoman corridas que hayan quedado a medias.
    en_curso = [tuple(k.split("|", 1)) for k, v in estado.items()
                if v.get("run_id") and not zona_hecha(*k.split("|", 1), estado)]
    cola = en_curso + [z for z in pendientes if z not in en_curso]
    if not cola:
        print("No quedan zonas por revisar.")
        return
    if n == 0 and not en_curso:
        return
    usado, maximo = api.credito()
    libre_inicial = maximo - usado
    print(f"\nVoy a revisar zonas hasta que se termine el crédito (USD {libre_inicial:.2f} disponibles; "
          f"cada zona cuesta entre USD 0,50 y {costo_zona():.2f}).")
    if confirmar and input("¿Arranco? (s/n) ").strip().lower() not in ("s", "si", "sí", "y"):
        sys.exit("Cancelado. No se gastó nada.")

    gastado, hechas_ahora = 0.0, 0
    for ciudad, zona in cola:
        k = clave(ciudad, zona)
        previo_k = estado.get(k, {})
        retomar = bool(previo_k.get("run_id"))
        if not retomar:
            # Antes de cada zona: ¿alcanza el crédito? Se toma lo menor entre lo que informa
            # Apify (que a veces tarda en actualizarse) y la cuenta propia de lo gastado.
            usado, maximo = api.credito()
            libre_cuenta = libre_inicial - gastado
            libre = min(maximo - usado, libre_cuenta) if usado is not None and maximo else libre_cuenta
            if libre - C.PROSP_MARGEN_USD < costo_zona():
                print(f"\nSe terminó el crédito: quedan USD {max(libre, 0):.2f}, no alcanza para otra zona.")
                break
        intentos = previo_k.get("vacia", 1 if previo_k.get("negocios") == 0 else 0)
        entrada = entrada_zona(zona if intentos == 0 else ubicacion_alternativa(zona))
        if retomar:
            run_id = previo_k["run_id"]
            print(f"\n{zona}: retomo la corrida que quedó a medias...")
        else:
            print(f"\n{zona}: arrancando...")
            try:
                run_id = api.arrancar(C.ACTOR_MAPS, entrada, costo_zona() * 1.1)["id"]
            except ErrorApify as e:
                print(f"  Apify no dejó arrancar la zona ({e}). Freno acá.")
                break
            estado[k] = {"run_id": run_id}
            guardar_json(ZONAS, estado)
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
        gastado += float(run.get("usageTotalUsd") or 0) or costo_zona()
        items = api.items(run["defaultDatasetId"])
        if not items:
            estado[k] = {"vacia": intentos + 1}
            guardar_json(ZONAS, estado)
            print(f"  {zona}: Google Maps no devolvió negocios. "
                  + ("La próxima vez pruebo escribiéndola distinto." if intentos == 0 else "La salteo."))
            continue
        guardar_json(archivo_zona(ciudad, zona), {
            "ciudad": ciudad, "zona": zona,
            "fecha": run.get("finishedAt") or datetime.now(timezone.utc).isoformat(),
            "run_id": run_id, "estado_corrida": run["status"],
            "completa": run["status"] == "SUCCEEDED", "entrada": entrada, "items": items,
        })
        estado[k] = {"hecha": True, "negocios": len(items)}
        guardar_json(ZONAS, estado)
        hechas_ahora += 1
        print(f"  {zona}: {len(items)} negocios ({run['status']}).")
        resumen_avance(api)
    print(f"\nListo: {hechas_ahora} zonas nuevas en esta corrida. Seguí con: py prospectar.py lista")


def resumen_avance(api):
    """Después de cada zona: crédito que queda y zonas que faltan."""
    todas = zonas_en_orden()
    hechas = sum(1 for z in todas if zona_hecha(*z))
    usado, maximo = api.credito()
    if usado is not None and maximo:
        libre = maximo - usado
        print(f"  Crédito: quedan USD {libre:.2f} | "
              f"zonas revisadas: {hechas} de {len(todas)}")
    else:
        print(f"  Zonas revisadas: {hechas} de {len(todas)} (no se pudo leer el crédito)")


# ---------------------------------------------------------------------------
# Lista de prospectos
# ---------------------------------------------------------------------------
def cargar_bloques():
    bloques = []
    for ciudad in C.PROSP_ZONAS:
        p = CRUDO / f"{ciudad}.json"           # lo que ya se bajó en el estudio, sin costo extra
        if p.exists():
            b = leer_json(p, {})
            b["zona"] = "estudio"
            bloques.append((ciudad, b))
    for p in sorted(CRUDO_P.glob("*.json")):
        b = leer_json(p, {})
        if b.get("ciudad") in C.PROSP_ZONAS:
            bloques.append((b["ciudad"], b))
    return bloques


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
                 "moving", "movers", "property", "management", "realty", "group", "services", "salon"}
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
        todos = (r or {}).get("emails") or ([r["email"]] if r and r.get("email") else [])
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
    nuevos = [f for f in filas if f["email"].lower() not in exportados]
    for f in nuevos:
        exportados[f["email"].lower()] = hoy
    guardar_json(EXPORTADOS, exportados)

    SALIDA.mkdir(exist_ok=True)
    escribir_csv(SALIDA / "prospectos_todos.csv", filas, COLUMNAS)
    if nuevos:
        escribir_csv(SALIDA / f"prospectos_nuevos_{hoy}.csv", nuevos, COLUMNAS)

    print(f"\n{'Rubro':<32}{'A':>5}{'B':>5}{'C':>5}{'Total':>7}")
    for r in C.PROSP_RUBROS:
        cuenta = [sum(1 for f in filas if f["rubro"] == r and f["prioridad"] == x) for x in "ABC"]
        print(f"{C.RUBROS[r]['nombre']:<32}" + "".join(f"{c:>5}" for c in cuenta) + f"{sum(cuenta):>7}")
    print(f"\nTotal: {len(filas)} prospectos | nuevos en esta lista: {len(nuevos)}")
    print(f"Archivos en: {SALIDA}")
    return filas, nuevos


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        if cmd == "estimar":
            cmd_estimar(Apify(token()))
        elif cmd == "buscar":
            cmd_buscar()
        elif cmd == "lista":
            cmd_lista()
        else:
            print(__doc__)
    except ErrorApify as e:
        sys.exit(f"\nError de Apify: {e}")


if __name__ == "__main__":
    main()
