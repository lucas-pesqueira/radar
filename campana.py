"""Campaña de mails: arma la tanda del día y lleva el registro de cada prospecto.

Uso (desde esta carpeta):
    py campana.py tanda              arma la tanda de hoy (verifica las reseñas en vivo con Apify)
    py campana.py tanda --prueba     igual, pero sin Apify y sin guardar nada (para probar)
    py campana.py tanda --forzar     arma aunque hoy sea fin de semana o feriado en EEUU
    py campana.py tanda --auto       para la nube: si hoy no toca tanda (feriado o ya armada) termina sin error,
                                     y si no puede subir el registro a GitHub termina con error
    py campana.py enviado MAIL       el mail armado para ese prospecto salió (lo usa el envío automático)
    py campana.py respondio MAIL     el negocio respondió: no recibe más seguimientos
    py campana.py baja MAIL          pidió no recibir más mails: no se le escribe nunca más (ni a nadie de su dominio)
    py campana.py rebote MAIL        el mail rebotó (dirección inválida): no se vuelve a usar
    py campana.py descartar MAIL     el mail armado no se manda (primer mail: se descarta; seguimiento: queda para otro día)
    py campana.py apify              crédito de cada cuenta de Apify (token_apify.txt, token_apify1.txt...)
    py campana.py verificar MAIL...  chequea si esas casillas existen (no guarda nada; cuesta centavos de Apify)
    py campana.py destrabar          destraba el freno de emergencia (después de revisar rebotes o bajas)
    py campana.py estado             resumen de la campaña
    py campana.py metricas           envíos, respuestas y tasa por rubro, ciudad y prioridad

La tanda queda en prospectos/campana/tandas/tanda_<fecha>.json, con la hora de envío de cada mail.
Con ese archivo Claude escribe los mails y los deja como borradores en la casilla de envío.
"""

import csv
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone

import config as C
from analisis import fecha
from apify import Apify, ErrorApify
from apify import Cuentas as _Cuentas
from estudio import BASE, guardar_json, leer_json, token, tokens
from prospectar import es_espanol, gancho

try:
    from zoneinfo import ZoneInfo
    ZoneInfo(C.ZONA_LUCAS)
except Exception:                                                   # Windows sin el paquete tzdata
    ZoneInfo = None

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

DATOS = BASE / "prospectos"        # repo privado aparte (radar-datos): se sincroniza entre PC
DIR = DATOS / "campana"
REGISTRO = DIR / "registro.json"
BAJAS = DIR / "bajas.json"
TANDAS = DIR / "tandas"
INVALIDOS = DIR / "mails_invalidos.json"   # mails que la verificación dio por inexistentes: no se vuelven a probar
PROSPECTOS = BASE / "prospectos" / "prospectos_todos.csv"
BACKUPS = BASE / "datos" / "backups"   # fuera de los dos repos: copias locales antes de cada cambio
ORDEN_PRIORIDAD = {"A": 0, "B": 1, "C": 2}
# Dominios de mail personal: una baja de alguien con gmail no bloquea a todo gmail.
DOMINIOS_LIBRES = {"gmail.com", "googlemail.com", "yahoo.com", "ymail.com", "hotmail.com", "outlook.com",
                   "live.com", "msn.com", "aol.com", "icloud.com", "me.com", "mac.com", "proton.me", "protonmail.com",
                   "comcast.net", "att.net", "sbcglobal.net", "verizon.net", "cox.net", "bellsouth.net"}
TIPOS_ENVIO = ("primer mail", "seguimiento 1", "seguimiento 2", "seguimiento 3")


def dominio(email):
    return str(email or "").strip().lower().rpartition("@")[2]


def dominio_empresa(email):
    """Dominio propio del negocio, o vacío si es un mail personal (gmail, yahoo...)."""
    d = dominio(email)
    return "" if not d or d in DOMINIOS_LIBRES else d


def dominios_bloqueados(bajas):
    """Dominios de empresa con al menos una baja: no se le escribe a nadie de ahí."""
    return {dominio_empresa(e) for e in bajas} - {""}


def esta_bloqueado(email, bajas, doms):
    return email.lower() in bajas or dominio(email) in doms


# ---------------------------------------------------------------------------
# Archivos: si algo está roto se frena, nunca se sigue con datos vacíos
# ---------------------------------------------------------------------------
def leer_estricto(p, defecto, tipo):
    """Lee un JSON del registro. Si no existe, devuelve el defecto. Si existe y está roto, corta:
    seguir con un registro vacío haría escribirle de nuevo a todos (o a quien pidió la baja)."""
    if not p.exists():
        return defecto
    try:
        datos = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        sys.exit(f"El archivo {p.name} está roto ({e}).\nNo sigo para no escribirle a quien no corresponde.\n"
                 f"Copias de seguridad en: {BACKUPS}\nRecuperalo (o pedile ayuda a Claude) antes de seguir.")
    if not isinstance(datos, tipo):
        sys.exit(f"El archivo {p.name} no tiene el formato esperado. No sigo.")
    return datos


def leer_registro():
    return leer_estricto(REGISTRO, {}, dict)


def leer_bajas():
    return {str(e).strip().lower() for e in leer_estricto(BAJAS, [], list)}


def guardar_seguro(p, datos):
    """Guarda haciendo antes una copia del archivo anterior (se guardan las últimas 60)."""
    if p.exists():
        BACKUPS.mkdir(parents=True, exist_ok=True)
        marca = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        shutil.copy2(p, BACKUPS / f"{p.stem}_{marca}.json")
        viejas = sorted(BACKUPS.glob(f"{p.stem}_*.json"))
        for v in viejas[:-60]:
            v.unlink(missing_ok=True)
    guardar_json(p, datos)


# ---------------------------------------------------------------------------
# Días hábiles en EEUU
# ---------------------------------------------------------------------------
def _n_esimo(anio, mes, dia_semana, n):
    """n-ésimo día de la semana del mes (n=-1: el último). dia_semana: 0 = lunes."""
    if n > 0:
        d = date(anio, mes, 1)
        d += timedelta(days=(dia_semana - d.weekday()) % 7)
        return d + timedelta(weeks=n - 1)
    d = date(anio + (mes == 12), mes % 12 + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - dia_semana) % 7)


def _observado(d):
    """Feriado fijo que cae en fin de semana: se toma el viernes o el lunes."""
    return d - timedelta(days=1) if d.weekday() == 5 else d + timedelta(days=1) if d.weekday() == 6 else d


def feriados_eeuu(anio):
    """Días en que no conviene escribir a un negocio chico de EEUU: {fecha: nombre}."""
    accion = _n_esimo(anio, 11, 3, 4)
    f = {
        _observado(date(anio, 1, 1)): "Año Nuevo",
        _n_esimo(anio, 5, 0, -1): "Memorial Day",
        _observado(date(anio, 7, 4)): "Día de la Independencia",
        _n_esimo(anio, 9, 0, 1): "Labor Day",
        accion: "Thanksgiving",
        accion + timedelta(days=1): "Black Friday",
        date(anio, 12, 24): "Nochebuena",
        _observado(date(anio, 12, 25)): "Navidad",
        date(anio, 12, 31): "Fin de año",
    }
    return {d: n for d, n in f.items() if d.weekday() < 5}


def motivo_no_habil(d):
    if d.weekday() >= 5:
        return "fin de semana"
    return feriados_eeuu(d.year).get(d, "")


def es_habil(d):
    return not motivo_no_habil(d)


def dias_habiles(desde, hasta):
    """Días hábiles en EEUU entre dos fechas, sin contar la primera."""
    n, d = 0, desde
    while d < hasta:
        d += timedelta(days=1)
        if es_habil(d):
            n += 1
    return n


def hoy():
    """Fecha de trabajo. Con RADAR_FECHA=AAAA-MM-DD se registra esa fecha (para preparar el envío de otro día)."""
    f = os.environ.get("RADAR_FECHA")
    return date.fromisoformat(f) if f else date.today()


# ---------------------------------------------------------------------------
# Armado -> enviado
# ---------------------------------------------------------------------------
def aplicar_envio(r, cuando):
    """Pasa un mail armado a enviado, con la fecha en que salió."""
    a = r.pop("armado")
    tipo = a["tipo"]
    if tipo == "primer mail":
        r["estado"] = "enviado"
        r["fechas"]["enviado"] = cuando
    else:
        r["estado"] = tipo
        r["fechas"][tipo] = cuando


def confirmar_armados(registro):
    """Mails armados en días anteriores que siguen como armados.
    - Sin envío automático (CONFIRMAR_AL_DIA_SIGUIENTE): se dan por enviados el día en que se armaron.
    - Con envío automático: si no salieron es porque no había borrador (no se aprobó). El primer mail
      se borra del registro (el negocio vuelve a estar disponible) y el seguimiento queda para otro día.
    Devuelve cuántos tocó."""
    n, d = 0, hoy().isoformat()
    for email in list(registro):
        r = registro[email]
        a = r.get("armado")
        if not a or a["fecha"] >= d:
            continue
        n += 1
        if C.CONFIRMAR_AL_DIA_SIGUIENTE:
            aplicar_envio(r, a["fecha"])
        elif a["tipo"] == "primer mail":
            del registro[email]
            print(f"  {email}: el primer mail del {a['fecha']} no salió; vuelve a la lista de prospectos.")
        else:
            r.pop("armado")
            print(f"  {email}: el {a['tipo']} del {a['fecha']} no salió; queda para el próximo día hábil.")
    return n


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


RUBRO_EN_NOMBRE = re.compile(
    r"\s+(?:&\s+)?(?:property\s+management(?:\s+(?:company|group|services|inc))?|management\s+(?:company|group|services)"
    r"|moving\s+(?:and|&)\s+storage|moving\s+(?:company|services)|movers(?:\s+inc)?)$", re.I)


def nombre_corto(negocio):
    """Para el saludo: 'Citiside Property Management' -> 'Citiside', 'Wirks Moving and Storage' ->
    'Wirks'. Solo saca el rubro del final si queda algo; restaurantes y salones quedan igual."""
    s = str(negocio or "").strip()
    corto = RUBRO_EN_NOMBRE.sub("", s).strip(" ,&-")
    return corto if re.search(r"[A-Za-z]{2,}", corto) else s


def vencido(p, hoy=None):
    """Los datos del negocio (columna datos_del) tienen más de PROSP_VENCE_DIAS: no se usa.
    Sin esa columna (listas viejas), cuenta como vigente."""
    d = str(p.get("datos_del") or "")[:10]
    if not d:
        return False
    try:
        bajado = datetime.strptime(d, "%Y-%m-%d").date()
    except ValueError:
        return False
    return ((hoy or datetime.now().date()) - bajado).days > C.PROSP_VENCE_DIAS


def cargar_prospectos(incluir_vencidos=False, ruta=None):
    ruta = ruta or PROSPECTOS
    if not ruta.exists():
        sys.exit("No hay lista de prospectos. Corré primero: py prospectar.py lista")
    with ruta.open(encoding="utf-8-sig") as f:
        filas = list(csv.DictReader(f))
    return filas if incluir_vencidos else [p for p in filas if not vencido(p)]


def lugares_guardados():
    """Último dato crudo de cada negocio (del estudio y de la prospección), por placeId."""
    import prospectar as P
    out = {}
    archivos = sorted(P.CRUDO.glob("*.json.gz")) + sorted(P.CRUDO_P.glob("*.json.gz"))
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
    run = api.arrancar(C.ACTOR_MAPS, entrada, tope_verificacion(len(place_ids)))
    inicio = time.time()

    def avanzar(_r):
        print(f"  verificando reseñas ({(time.time() - inicio) / 60:.0f} min)...")

    run = api.esperar(run["id"], avanzar, cada=20)
    items = api.items(run["defaultDatasetId"])
    return {l.get("placeId"): l for l in items if l.get("placeId")}


def verificar_mails(api, emails):
    """Chequea por SMTP (actor de Apify) que cada casilla exista. Devuelve {email: estado}, con estado
    "valid", "invalid", "catch-all", "risky" o "unknown". Lo que no vuelve queda como "unknown"."""
    entrada = {"emails": list(emails), "checkCatchAll": True, "timeoutSecs": 30, "concurrency": 5}
    run = api.arrancar(C.ACTOR_MAILS, entrada, tope_mails(len(emails)))
    run = api.esperar(run["id"], cada=10)
    estados = {e.lower(): "unknown" for e in emails}
    for it in api.items(run["defaultDatasetId"]):
        e = str(it.get("email", "")).strip().lower()
        if e in estados:
            estados[e] = str(it.get("status") or "unknown").lower()
    return estados


def tope_mails(n):
    """Lo que se reserva en Apify para verificar n mails (Apify exige un tope mínimo de USD 0,50)."""
    return max(0.5, n * C.PRECIO_MAIL * 1.5 + 0.05)


def leer_invalidos():
    return {str(k).lower(): v for k, v in leer_estricto(INVALIDOS, {}, dict).items()}


def filtrar_mails(listos, cuentas, prueba):
    """Saca de 'listos' (lista de (item, dominio)) los mails que la verificación da por inexistentes.
    Devuelve (buenos, malos). Si la verificación falla, no frena la tanda: pasan todos."""
    if prueba or not C.VERIFICAR_MAILS or not listos:
        return listos, []
    emails = [it["email"] for it, _ in listos]
    cuenta = cuentas.para(tope_mails(len(emails)))
    if not cuenta:
        print("  OJO: no alcanza el crédito de Apify para verificar los mails; salen sin verificar.")
        return listos, []
    print(f"Verificando {len(emails)} mails (cuenta {cuenta['n']}, como máximo USD {tope_mails(len(emails)):.2f})...")
    try:
        estados = verificar_mails(cuenta["api"], emails)
    except ErrorApify as e:
        print(f"  OJO: falló la verificación de mails ({e}); salen sin verificar.")
        return listos, []
    VERIFICACION["gasto"] += len(emails) * C.PRECIO_MAIL
    buenos, malos = [], []
    for it, de in listos:
        estado = estados.get(it["email"].lower(), "unknown")
        it["mail_verificado"] = estado
        (malos if estado == "invalid" else buenos).append((it, de))
    if malos:
        invalidos = leer_invalidos()
        for it, _ in malos:
            invalidos[it["email"].lower()] = hoy().isoformat()
        guardar_seguro(INVALIDOS, invalidos)
    return buenos, malos


# ---------------------------------------------------------------------------
# Horario de envío
# ---------------------------------------------------------------------------
_DESFASE_INVIERNO = {"America/New_York": -5, "America/Chicago": -6, "America/Phoenix": -7,
                     "America/Los_Angeles": -8}


def zona_ciudad(ciudad):
    c = str(ciudad or "").lower()
    for clave, z in C.ZONAS_CIUDAD.items():
        if clave in c:
            return z
    return "America/New_York"


def _a_utc(d, hora, minuto, zona):
    if ZoneInfo:
        return datetime(d.year, d.month, d.day, hora, minuto, tzinfo=ZoneInfo(zona)).astimezone(timezone.utc)
    # Sin tzdata: se asume horario de invierno de EEUU (noviembre a marzo).
    return datetime(d.year, d.month, d.day, hora, minuto, tzinfo=timezone.utc) - timedelta(hours=_DESFASE_INVIERNO.get(zona, -5))


def _a_lucas(dt):
    if ZoneInfo:
        return dt.astimezone(ZoneInfo(C.ZONA_LUCAS))
    return dt.astimezone(timezone(timedelta(hours=-3)))


def _hm(texto):
    h, m = map(int, texto.split(":"))
    return h, m


def _ventana_art(d):
    """La ventana del envío automático de ese día, en UTC."""
    art = timezone(timedelta(hours=-3))                 # Argentina no cambia de hora
    (h1, m1), (h2, m2) = _hm(C.VENTANA_ART[0]), _hm(C.VENTANA_ART[1])
    return (datetime(d.year, d.month, d.day, h1, m1, tzinfo=art).astimezone(timezone.utc),
            datetime(d.year, d.month, d.day, h2, m2, tzinfo=art).astimezone(timezone.utc))


def franjas(it, d, zona):
    """Franjas de envío del rubro del ítem, en UTC y recortadas a la ventana del envío automático."""
    lo, hi = _ventana_art(d)
    out = []
    for desde, hasta in C.HORARIOS_RUBRO.get(rubro_clave(it.get("rubro")), C.HORARIOS_DEFECTO):
        a, b = max(_a_utc(d, *_hm(desde), zona), lo), min(_a_utc(d, *_hm(hasta), zona), hi)
        if a < b:
            out.append((a, b))
    return out or [(lo, hi)]


def asignar_horarios(items, d):
    """Cada mail sale en la franja de su rubro (hora local de su ciudad), escalonado dentro de cada ciudad
    y nunca en punto. Si la primera franja se llena, va a la segunda.
    Agrega 'hora_art' (para programar en Gmail desde Argentina) y 'envio_utc'."""
    azar = random.Random(f"{d.isoformat()}-{len(items)}")
    lo, hi = _ventana_art(d)
    por_zona = {}
    for it in items:
        por_zona.setdefault(zona_ciudad(it.get("ciudad")), []).append(it)
    for zona, lista in por_zona.items():
        ocupados = []                                   # horarios ya dados en esta ciudad
        # primero los de franja que cierra antes (restaurantes): así entran todos a la mañana si se puede
        lista = sorted(lista, key=lambda it: (franjas(it, d, zona)[0][1], franjas(it, d, zona)[0][0]))
        def hueco(desde, hasta):
            """El primer horario libre (a SEPARACION_MIN de los demás de la ciudad) entre desde y hasta, o None."""
            c = desde + timedelta(minutes=azar.randint(2, 9))
            for o in sorted(ocupados):
                if abs((c - o).total_seconds()) < C.SEPARACION_MIN[0] * 60:
                    c = o + timedelta(minutes=azar.randint(*C.SEPARACION_MIN))
            return c if c <= hasta else None

        for it in lista:
            fr = franjas(it, d, zona)
            t = next((h for h in (hueco(a, b) for a, b in fr) if h), None)
            if t is None:                               # no entra en su rubro: después de su última franja
                t = hueco(fr[-1][1], hi) or hueco(lo, hi) or hi   # (no al mediodía) o el primer hueco del día
            if _a_lucas(t).minute in (0, 30):           # nunca en punto ni a la media
                t += timedelta(minutes=1)
            ocupados.append(t)
            it["hora_art"] = _a_lucas(t).strftime("%H:%M")
            it["envio_utc"] = t.isoformat()
    return items


# ---------------------------------------------------------------------------
# Tanda
# ---------------------------------------------------------------------------
def seguimientos_pendientes(registro):
    """Prospectos a los que hoy les toca un seguimiento (los que ya tienen un mail armado no)."""
    out, d = [], hoy()
    for email, r in registro.items():
        if r.get("estado") not in ("enviado", "seguimiento 1", "seguimiento 2") or r.get("armado"):
            continue
        primero = date.fromisoformat(r["fechas"]["enviado"])
        transcurridos = dias_habiles(primero, d)
        if r["estado"] == "enviado" and transcurridos >= C.SEGUIMIENTO_DIAS[0]:
            out.append((email, 1))
        elif r["estado"] == "seguimiento 1" and transcurridos >= C.SEGUIMIENTO_DIAS[1]:
            # Si el primer seguimiento salió tarde, el segundo espera igual su distancia mínima.
            desde_seg1 = r["fechas"].get("seguimiento 1")
            if not desde_seg1 or dias_habiles(date.fromisoformat(desde_seg1), d) >= C.SEGUIMIENTO_DIAS[1] - C.SEGUIMIENTO_DIAS[0]:
                out.append((email, 2))
        elif r["estado"] == "seguimiento 2" and transcurridos >= C.SEGUIMIENTO_DIAS[2]:
            desde_seg2 = r["fechas"].get("seguimiento 2") or ""
            if desde_seg2 < C.SEG3_DESDE:
                continue                     # su seguimiento 2 prometía que era el último
            if dias_habiles(date.fromisoformat(desde_seg2), d) >= C.SEGUIMIENTO_DIAS[2] - C.SEGUIMIENTO_DIAS[1]:
                out.append((email, 3))
    out.sort(key=lambda x: registro[x[0]]["fechas"]["enviado"])
    return out


def mails_de_hoy(registro, d):
    """Mails que salen hoy: armados para hoy y enviados hoy. Rebotes y bajas no cuentan."""
    out = set()
    for e, r in registro.items():
        if r.get("estado") == "descartado":
            continue
        if (r.get("armado") or {}).get("fecha") == d:
            out.add(e)
        elif any(v == d for k, v in r.get("fechas", {}).items() if k == "enviado" or k.startswith("seguimiento")):
            out.add(e)
    return out


def evaluar(p, lugar, cuando, verificado):
    """Arma el ítem de primer mail o devuelve el motivo para saltearlo."""
    if lugar.get("permanentlyClosed") or lugar.get("temporarilyClosed"):
        return None, "cerrado"
    g = gancho(lugar, cuando)
    if not g:
        return None, "ya respondió sus reseñas"
    muestra = len([r for r in (lugar.get("reviews") or [])
                   if str(r.get("reviewOrigin") or "Google").lower() == "google"])
    resenas = [{"autor": nombre_autor(g["gancho_autor"]), "estrellas": g["gancho_estrellas"],
                "fecha": g["gancho_fecha"], "texto": g["gancho_texto"]}]
    if g.get("gancho2_fecha"):
        resenas.append({"autor": nombre_autor(g["gancho2_autor"]), "estrellas": g["gancho2_estrellas"],
                        "fecha": g["gancho2_fecha"], "texto": g["gancho2_texto"]})
    return {
        "tipo": "primer mail", "email": p["email"].strip().lower(), "negocio": nombre_prolijo(p["nombre"]),
        "negocio_corto": nombre_corto(nombre_prolijo(p["nombre"])),
        "negocio_original": p["nombre"], "rubro": p["rubro_nombre"],
        "precio": C.PRECIO_RUBRO.get(rubro_clave(p["rubro_nombre"])),
        "ciudad": p["ciudad_nombre"], "prioridad": p["prioridad"],
        "sin_responder": g["sin_responder_muestra"], "de_las_ultimas": muestra,
        "resenas": resenas, "en_espanol": es_espanol(" ".join(r["texto"] for r in resenas)),
        "verificado": verificado, "place_id": p["place_id"], "maps": p.get("maps", ""),
    }, ""


def responde_resenas(lugar):
    """True si el negocio responde sus reseñas, False si no, None si hay muy pocas para saber."""
    rv = [r for r in (lugar.get("reviews") or []) if str(r.get("reviewOrigin") or "Google").lower() == "google"]
    if len(rv) < C.COMP_MIN_RESENAS:
        return None
    hechas = sum(1 for r in rv if str(r.get("responseFromOwnerText") or "").strip())
    return hechas / len(rv) >= C.COMP_TASA


def indice_competencia():
    """{placeId: lista de negocios de la misma búsqueda (rubro) en la misma zona}, de lo que bajó la prospección."""
    import prospectar as P
    out = {}
    for p in sorted(P.CRUDO_P.glob("*.json.gz")):
        grupos = {}
        for l in leer_json(p, {}).get("items", []):
            if l.get("placeId"):
                grupos.setdefault(str(l.get("searchString") or "").lower(), []).append(l)
        for lista in grupos.values():
            for l in lista:
                out[l["placeId"]] = lista
    return out


def del_rubro(lugar):
    """La categoría de Google del negocio es del rubro que se buscó (no un bar en la búsqueda de restaurantes)."""
    palabras = C.COMP_CATEGORIA.get(str(lugar.get("searchString") or "").lower())
    if not palabras:
        return True
    cat = str(lugar.get("categoryName") or "").lower()          # solo la principal: las otras son muy amplias
    return any(p in cat for p in palabras)


def es_cadena(nombre):
    n = str(nombre or "").lower()
    return any(m in n for m in C.MARCAS_CADENA)


def _simple(nombre):
    return re.sub(r"[^a-z0-9]", "", str(nombre or "").lower())


def competencia(place_id, indice):
    """Cuántos de los vecinos más cercanos del mismo rubro responden sus reseñas, y el más cercano que lo hace.
    Devuelve {} si no hay datos o si son menos de COMP_MIN (no ayuda mencionarlo)."""
    lista = indice.get(place_id) or []
    yo = next((l for l in lista if l.get("placeId") == place_id), None)
    loc = (yo or {}).get("location") or {}
    if not yo or "lat" not in loc or "lng" not in loc:
        return {}
    vecinos = []
    for l in lista:
        o = l.get("location") or {}
        if (l is yo or "lat" not in o or l.get("permanentlyClosed") or l.get("temporarilyClosed")
                or _simple(l.get("title")) == _simple(yo.get("title"))       # otra sucursal del mismo
                or not del_rubro(l) or es_cadena(l.get("title"))):
            continue
        estado = responde_resenas(l)
        if estado is None:
            continue
        # distancia aproximada (alcanza para ordenar dentro de un barrio)
        dist = (o["lat"] - loc["lat"]) ** 2 + ((o["lng"] - loc["lng"]) * math.cos(math.radians(loc["lat"]))) ** 2
        vecinos.append((dist, estado, l))
    vecinos.sort(key=lambda x: x[0])
    cerca = vecinos[:C.COMP_VECINOS]
    responden = [l for _, ok, l in cerca if ok]
    if len(cerca) < C.COMP_VECINOS or len(responden) < C.COMP_MIN:
        return {}
    ejemplos = [n for n in (nombre_ejemplo(l.get("title")) for l in responden) if n]
    if not ejemplos:
        return {}
    return {"comp_responden": len(responden), "comp_de": len(cerca), "comp_ejemplo": ejemplos[0]}


def nombre_ejemplo(titulo):
    """Nombre del vecino para citarlo, o "" si no queda presentable."""
    n = re.split(r"\s*[-–—|]\s+|\s+[-–—|]\s*", nombre_prolijo(titulo))[0].strip(" ,.-")
    if len(re.sub(r"[^A-Za-z]", "", n)) < 3 or len(n) > 40:
        return ""
    return n


VERIFICACION = {"rondas": 0, "gasto": 0.0, "credito_libre": None}   # lo de la última tanda (para alertas)


def Cuentas(lista=None):
    """Las cuentas de Apify (ver apify.Cuentas): por defecto, todos los tokens en orden."""
    return _Cuentas(lista if lista is not None else tokens(), fabrica=lambda t: Apify(t))


def cmd_apify():
    """Muestra el crédito de cada cuenta de Apify (sin mostrar los tokens)."""
    cu = Cuentas()
    for c in cu.cuentas:
        print(f"Cuenta {c['n']}: usado USD {c['usado']:.2f} de {c['maximo']:.2f} este mes (libre USD {c['libre']:.2f})")
    if not cu.cuentas:
        sys.exit("Ninguna cuenta de Apify responde: revisá los tokens.")
    print(f"Total libre: USD {cu.libre_total():.2f}")


def cmd_verificar(emails):
    """Chequea a mano si unas casillas existen. No toca el registro."""
    emails = [e.strip().lower() for e in emails]
    cuenta = Cuentas().para(tope_mails(len(emails)))
    if not cuenta:
        sys.exit("No alcanza el crédito de Apify para verificar.")
    for e, estado in verificar_mails(cuenta["api"], emails).items():
        print(f"  {e}: {estado}")


def tope_verificacion(n):
    """Lo que se reserva en Apify por corrida: Apify exige un tope mínimo de USD 0,50."""
    return max(0.5, costo_verificacion(n) * 1.2 + 0.01)


def elegir_nuevos(cand, cupo, prueba, doms_usados):
    """Recorre los candidatos en rondas (verificando con Apify) hasta llenar el cupo."""
    VERIFICACION.update(rondas=0, gasto=0.0, credito_libre=None)
    cuentas = None
    nuevos, salteados, pos, rondas = [], [], 0, 0
    guardados = None
    indice = None
    api = None
    probados = servidos = 0
    while len(nuevos) < cupo and pos < len(cand):
        faltan = cupo - len(nuevos)
        # Cuántos verificar: según cuántos sirvieron hasta ahora (al principio se asume 3 de cada 4).
        tasa = servidos / probados if probados else 0.75
        tamanio = min(200, int(faltan / max(tasa, 0.1) * 1.2) + 3)
        lote = cand[pos:pos + tamanio]
        pos += len(lote)
        frescos = {}
        if not prueba:
            if rondas >= C.VERIFICAR_RONDAS:
                print(f"  Se llegó al máximo de {C.VERIFICAR_RONDAS} verificaciones: la tanda queda con "
                      f"{len(nuevos)} primeros mails de {cupo}.")
                break
            rondas += 1
            ids = [p["place_id"] for p in lote if re.match(r"^(ChIJ|GhIJ)", p["place_id"])]
            if ids:
                cuentas = cuentas or Cuentas()
                costo = tope_verificacion(len(ids))
                cuenta = cuentas.para(costo)
                VERIFICACION["credito_libre"] = cuentas.libre_total()
                if not cuenta:
                    sys.exit(f"No alcanza el crédito de Apify para verificar (hace falta USD {costo:.2f}; "
                             f"entre todas las cuentas quedan USD {cuentas.libre_total():.2f}).")
                print(f"Verificando {len(ids)} negocios en Google Maps (ronda {rondas}, cuenta {cuenta['n']}, "
                      f"como máximo USD {costo:.2f})...")
                frescos = verificar(cuenta["api"], ids)
                VERIFICACION["rondas"] = rondas
                VERIFICACION["gasto"] += costo
        ahora = datetime.now(timezone.utc)
        listos = []
        for p in lote:
            if len(nuevos) + len(listos) >= cupo:
                break
            probados += 1
            de = dominio_empresa(p["email"])
            if de and de in doms_usados:
                salteados.append((p["nombre"], "otro negocio del mismo dominio ya está en la campaña"))
                continue
            pid = p["place_id"]
            if pid in frescos:
                lugar, cuando, verificado = frescos[pid], ahora, True
            else:
                if guardados is None:
                    guardados = lugares_guardados()
                if pid not in guardados:
                    salteados.append((p["nombre"], "sin datos del negocio"))
                    continue
                (lugar, cuando), verificado = guardados[pid], False
                if not prueba:
                    salteados.append((p["nombre"], "Google Maps no lo devolvió al verificar"))
                    continue
            it, motivo = evaluar(p, lugar, cuando, verificado)
            if not it:
                salteados.append((p["nombre"], motivo))
                continue
            if indice is None:
                indice = indice_competencia()
            it.update(competencia(pid, indice))
            listos.append((it, de))
            servidos += 1
            if de:
                doms_usados.add(de)
        if listos and not prueba and C.VERIFICAR_MAILS:
            cuentas = cuentas or Cuentas()
        buenos, malos = filtrar_mails(listos, cuentas, prueba)
        nuevos += [it for it, _ in buenos]
        for it, de in malos:
            salteados.append((it["negocio"], f"el mail {it['email']} no existe (verificación)"))
            if de:
                doms_usados.discard(de)
    return nuevos, salteados


def archivo_tanda(d, prueba):
    if prueba:
        return TANDAS / f"tanda_{d}_prueba.json"
    archivo = TANDAS / f"tanda_{d}.json"
    n = 1
    while archivo.exists():                                         # tanda completada el mismo día: no pisar la anterior
        archivo = TANDAS / f"tanda_{d}_completar{'' if n == 1 else n}.json"
        n += 1
    return archivo


def _nada_que_hacer(mensaje, auto):
    """Sin --auto corta con aviso; con --auto (la nube) lo informa y termina bien: no es un error."""
    if auto:
        print(mensaje)
        return None
    sys.exit(mensaje)


def limite_del_dia(registro, dia, freno=False):
    """Tope de mails de hoy según la subida gradual (C.RAMPA). Devuelve (tope, explicación)."""
    d = dia.isoformat()
    escalones = [n for f, n in C.RAMPA if f <= d] or [C.ENVIOS_POR_DIA]
    tope = escalones[-1]
    if len(escalones) == 1:
        return tope, f"tope {tope}"
    desde = (dia - timedelta(days=C.RAMPA_DIAS)).isoformat()
    primeros = [r for r in registro.values() if desde <= (r.get("fechas") or {}).get("enviado", "") < d]
    rebotes = sum(1 for r in primeros if r.get("estado") == "rebotó")
    tasa = rebotes / len(primeros) if primeros else 0.0
    if freno or tasa >= C.RAMPA_REBOTE_MAX:
        motivo = "freno activo" if freno else f"rebotes {rebotes}/{len(primeros)} ({tasa:.0%})"
        return escalones[-2], f"tope {escalones[-2]} en vez de {tope} ({motivo})"
    return tope, f"tope {tope} (rebotes {rebotes}/{len(primeros)} en {C.RAMPA_DIAS} días)"


def cmd_tanda(prueba=False, limite=None, forzar=False, auto=False):
    explicacion_tope = ""
    if not limite:
        import control as X
        limite, explicacion_tope = limite_del_dia(leer_registro(), hoy(), X.freno_activo())
    dia = hoy()
    d = dia.isoformat()
    motivo = motivo_no_habil(dia)
    if motivo and not forzar:
        return _nada_que_hacer(f"El {d} no es día hábil en EEUU ({motivo}): no se arma tanda. "
                               f"Si igual querés armarla: py campana.py tanda --forzar", auto)
    registro = leer_registro()
    bajas = leer_bajas()
    confirmar_armados(registro)
    doms = dominios_bloqueados(bajas)
    ya_hoy = mails_de_hoy(registro, d)
    if ya_hoy and not prueba:
        limite -= len(ya_hoy)
        if limite <= 0:
            return _nada_que_hacer(f"Ya se armó la tanda de hoy ({len(ya_hoy)} mails). "
                                   f"La próxima, el próximo día hábil.", auto)
        print(f"Hoy ya hay {len(ya_hoy)} mails armados: se arman {limite} más para completar el cupo.")

    # 1) Seguimientos primero: son los que ya están en conversación.
    todos_segs = [(e, n) for e, n in seguimientos_pendientes(registro) if not esta_bloqueado(e, bajas, doms)]
    segs = todos_segs[:limite]
    items = []
    for email, n in segs:
        r = registro[email]
        items.append({"tipo": f"seguimiento {n}", "email": email, "negocio": r["negocio"],
                      "negocio_corto": nombre_corto(r["negocio"]),
                      "rubro": r["rubro"], "precio": r["precio"], "ciudad": r["ciudad"],
                      "asunto": r["asunto"], "enviado": r["fechas"]["enviado"]})

    # 2) Prospectos nuevos para completar el cupo (salvo con el freno de emergencia activo).
    import control as X
    cupo = limite - len(items)
    nuevos, salteados = [], []
    if cupo > 0 and X.freno_activo() and not prueba:
        print(f"FRENO ACTIVO ({X.leer_freno().get('motivo')}): hoy solo seguimientos, sin primeros mails. "
              f"Revisalo y destrabalo con: py campana.py destrabar")
        cupo = 0
    if cupo > 0:
        contactados = set(registro) | bajas | set(leer_invalidos())
        doms_usados = set(doms) | {dominio_empresa(e) for e, r in registro.items()
                                   if r.get("estado") != "descartado"} - {""}
        from emails import es_basura
        cand = [p for p in cargar_prospectos() if p["email"].strip().lower() not in contactados
                and not es_basura(p["email"])]                  # mails de relleno de las webs (example@mail.com)
        cand = intercalar_rubros(cand)
        nuevos, salteados = elegir_nuevos(cand, cupo, prueba, doms_usados)
    items += nuevos
    asignar_horarios(items, dia)

    tanda = {"fecha": d, "prueba": prueba, "items": items,
             "salteados": [{"negocio": n, "motivo": m} for n, m in salteados]}
    TANDAS.mkdir(parents=True, exist_ok=True)
    archivo = archivo_tanda(d, prueba)
    guardar_json(archivo, tanda)

    if not prueba:
        for it in nuevos:
            registro[it["email"]] = {
                "negocio": it["negocio"], "rubro": it["rubro"], "precio": it["precio"],
                "ciudad": it["ciudad"], "place_id": it["place_id"], "prioridad": it.get("prioridad", ""),
                "asunto": f"{it['negocio']}'s Google reviews",
                "estado": "armado", "fechas": {"armado": d},
                "armado": {"tipo": "primer mail", "fecha": d, "envio_utc": it["envio_utc"]},
            }
        for it in items:
            if it["tipo"] != "primer mail":
                registro[it["email"]]["armado"] = {"tipo": it["tipo"], "fecha": d, "envio_utc": it["envio_utc"]}
        guardar_seguro(REGISTRO, registro)
        X.anotar_tanda(d, {"fecha": d, "primeros": len(nuevos), "nuevos": len(nuevos),
                           "seguimientos": len(segs), "cupo_nuevos": max(cupo, 0),
                           "salteados": len(salteados), "rondas": VERIFICACION["rondas"],
                           "gasto_estimado": round(VERIFICACION["gasto"], 2),
                           "credito_libre": VERIFICACION["credito_libre"],
                           "freno": X.freno_activo(), "tope": limite})
        m = X.actualizar(registro, bajas, d)
        for a in m["alertas"]:
            print(f"  ALERTA: {a}")

    print(f"\nTanda de {d}{' (prueba)' if prueba else ''}: {len(nuevos)} primeros mails + {len(segs)} seguimientos"
          f" = {len(items)} de {limite}" + (f" [{explicacion_tope}]" if explicacion_tope else ""))
    if len(todos_segs) > len(segs):
        print(f"  Quedan {len(todos_segs) - len(segs)} seguimientos para el próximo día hábil (no entraron en el cupo).")
    for n, m in salteados:
        print(f"  salteado: {n} ({m})")
    for it in items:
        print(f"  {it['hora_art']}  {it['tipo']:<14} {it['negocio']} ({it['ciudad']})")
    print(f"Archivo: {archivo}")
    if not auto:
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
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}", email):
        sys.exit(f"'{email}' no parece un mail. Revisalo.")
    registro = leer_registro()
    confirmar_armados(registro)
    if estado == "baja":
        bajas = leer_estricto(BAJAS, [], list)
        if email not in [str(b).lower() for b in bajas]:
            bajas.append(email)
            guardar_seguro(BAJAS, bajas)
    if email not in registro:
        if estado != "baja":
            sys.exit(f"{email} no está en el registro.")
        print(f"{email}: baja (no estaba en el registro; igual queda bloqueado).")
        return
    r = registro[email]
    a = r.get("armado")
    if estado == "enviado":
        if not a:
            sys.exit(f"{email} no tiene ningún mail armado.")
        aplicar_envio(r, hoy().isoformat())
        print(f"{email}: {r['estado']} ({hoy().isoformat()}).")
    elif estado == "descartado" and a and a["tipo"] != "primer mail":
        r.pop("armado")
        print(f"{email}: se canceló el {a['tipo']} armado para el {a['fecha']}. Queda para el próximo día hábil.")
    else:
        if a:
            r.pop("armado")
            if estado != "descartado":
                print(f"  OJO: tenía un {a['tipo']} armado para el {a['fecha']}. Ya no sale; si hay un borrador en Gmail, borralo.")
        r["estado"] = estado
        r["fechas"][estado] = hoy().isoformat()
        print(f"{email}: {estado}.")
    guardar_seguro(REGISTRO, registro)


def registro_vigente():
    """Registro para mirar (sin guardar): con los armados viejos ya confirmados y sin descartados."""
    registro = leer_registro()
    confirmar_armados(registro)
    return {k: v for k, v in registro.items() if v.get("estado") != "descartado"}


def cmd_estado():
    registro = registro_vigente()
    bajas = leer_bajas()
    cuenta = {}
    for r in registro.values():
        cuenta[r["estado"]] = cuenta.get(r["estado"], 0) + 1
    armados = sum(1 for r in registro.values() if r.get("armado"))
    total = len(cargar_prospectos()) if PROSPECTOS.exists() else 0
    enviados = len([r for r in registro.values() if r["estado"] != "armado"])
    print(f"Prospectos en la lista: {total} | contactados: {enviados} | bajas: {len(bajas)}")
    for e, n in sorted(cuenta.items()):
        print(f"  {e}: {n}")
    if armados:
        print(f"Mails armados esperando salir: {armados}")
    resp = cuenta.get("respondió", 0)
    if enviados:
        print(f"Tasa de respuesta: {100 * resp / enviados:.1f}%")
    import control as X
    for a in X.calcular(leer_registro(), bajas, hoy().isoformat())["alertas"]:
        print(f"ALERTA: {a}")


def cmd_metricas():
    """Envíos, respuestas y tasa por rubro, ciudad y prioridad. Con pocos envíos los números son ruido."""
    registro = {k: v for k, v in registro_vigente().items() if v.get("estado") != "armado"}
    if not registro:
        print("Todavía no hay envíos registrados.")
        return
    print(f"Envíos: {len(registro)}. Con menos de ~100 envíos por grupo, las diferencias no son confiables.")
    for titulo, campo in (("Rubro", "rubro"), ("Ciudad", "ciudad"), ("Prioridad", "prioridad")):
        grupos = {}
        for r in registro.values():
            g = grupos.setdefault(r.get(campo) or "(sin dato)", {"env": 0, "resp": 0, "baja": 0, "reb": 0})
            g["env"] += 1
            g["resp"] += 1 if "respondió" in r.get("fechas", {}) else 0
            g["baja"] += 1 if r.get("estado") == "baja" else 0
            g["reb"] += 1 if r.get("estado") == "rebotó" else 0
        print(f"\nPor {titulo.lower()}:")
        for nombre, g in sorted(grupos.items(), key=lambda x: -x[1]["env"]):
            print(f"  {nombre}: {g['env']} enviados | {g['resp']} respondieron ({100 * g['resp'] / g['env']:.0f}%)"
                  f" | {g['baja']} bajas | {g['reb']} rebotes")


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


def sync_despues(mensaje, estricto=False):
    """Sube el registro para que la otra PC lo vea. Si falla, lo avisa fuerte (con estricto, termina con error)."""
    if not _usa_git() or not DIR.exists():
        return
    _git("add", "-A")
    if _git("diff", "--cached", "--quiet").returncode == 0:
        return
    c = _git("commit", "-m", mensaje)
    p = _git("push") if c.returncode == 0 else c
    if p.returncode != 0:
        if estricto:
            sys.exit("El registro NO se subió a GitHub:\n" + (p.stderr or p.stdout).strip())
        print("\n!!! ATENCIÓN: el registro NO se subió a GitHub. No uses la otra PC hasta resolverlo.\n"
              + (p.stderr or p.stdout).strip() + "\nProbá a mano: git push")
    else:
        print("Registro subido a GitHub.")


MARCAS = {"respondio": "respondió", "respondió": "respondió", "baja": "baja", "rebote": "rebotó",
          "rebotó": "rebotó", "descartar": "descartado", "descartado": "descartado", "enviado": "enviado"}


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else ""
    try:
        if cmd == "tanda":
            prueba = "--prueba" in args
            auto = "--auto" in args
            sync_antes()
            hecha = cmd_tanda(prueba=prueba, forzar="--forzar" in args, auto=auto)
            if hecha and not prueba:
                sync_despues(f"Tanda {hoy().isoformat()}", estricto=auto)
        elif cmd == "apify":
            cmd_apify()
        elif cmd == "verificar" and len(args) > 1:
            cmd_verificar(args[1:])
        elif cmd == "destrabar":
            import control as X
            sync_antes()
            if X.destrabar(hoy().isoformat()):
                X.actualizar(leer_registro(), leer_bajas(), hoy().isoformat())
                sync_despues("Freno destrabado")
        elif cmd in MARCAS and len(args) > 1:
            import control as X
            sync_antes()
            cmd_marcar(args[1], MARCAS[cmd])
            X.actualizar(leer_registro(), leer_bajas(), hoy().isoformat())
            sync_despues(f"{MARCAS[cmd].capitalize()} {args[1]}")
        elif cmd == "estado":
            sync_antes()
            cmd_estado()
        elif cmd in ("metricas", "métricas"):
            sync_antes()
            cmd_metricas()
        else:
            print(__doc__)
    except ErrorApify as e:
        sys.exit(f"\nError de Apify: {e}")


if __name__ == "__main__":
    main()
