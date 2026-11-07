"""Del dato crudo de Google Maps a métricas por negocio, rubro y ciudad."""

import re
import statistics
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from urllib.parse import urlparse

import config as C


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def fecha(s):
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s.lower()).strip()


def mediana(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def pct(a, b):
    return round(100 * a / b, 1) if b else None


def redondo(x, d=2):
    return None if x is None else round(x, d)


# ---------------------------------------------------------------------------
# Web: tipo y clave para detectar cadenas
# ---------------------------------------------------------------------------
def _host_termina(host, sufijo):
    return host == sufijo or host.endswith("." + sufijo)


def analizar_web(url):
    """Devuelve (tipo, clave): tipo es 'sin_web', 'red_social' o 'propia'."""
    if not url or not str(url).strip():
        return "sin_web", None
    u = str(url).strip()
    if not re.match(r"^https?://", u, re.I):
        u = "http://" + u
    p = urlparse(u)
    host = (p.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return "sin_web", None
    if any(_host_termina(host, h) for h in C.HOSTS_NO_WEB):
        return "red_social", None
    if any(_host_termina(host, h) for h in C.HOSTS_CONSTRUCTOR):
        if host == "sites.google.com":
            seg = [x for x in p.path.split("/") if x]
            return "propia", host + "/" + "/".join(seg[:2])
        return "propia", host
    partes = host.split(".")
    return "propia", ".".join(partes[-2:]) if len(partes) >= 2 else host


# ---------------------------------------------------------------------------
# Rubro: ¿el resultado de Maps es realmente del rubro?
# ---------------------------------------------------------------------------
def categoria_valida(lugar, rubro):
    r = C.RUBROS[rubro]
    cats = [norm(c) for c in (lugar.get("categories") or []) if c]
    principal = norm(lugar.get("categoryName"))
    if principal and principal not in cats:
        cats.insert(0, principal)
    if not cats:
        return False
    if any(x in principal for x in r["excluir"]):
        return False
    return any(k in c for c in cats for k in r["categorias"])


def es_marca_cadena(titulo, dominio=None):
    t = norm(titulo)
    d = re.sub(r"[^a-z0-9]", "", (dominio or "").split(".")[0]) if dominio else ""
    for m in C.MARCAS_CADENA:
        m = norm(m)
        if re.search(r"(^|[^a-z0-9])" + re.escape(m) + r"($|[^a-z0-9])", t):
            return m
        compacta = re.sub(r"[^a-z0-9]", "", m)
        if d and len(compacta) >= 5 and compacta in d:
            return m
    return None


ESTADOS_US = {"al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id", "il", "in", "ia",
              "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
              "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "vt",
              "va", "wa", "wv", "wi", "wy"}


def web_de_sucursales(url):
    """Webs de empresas con varias sucursales: la ficha de Maps apunta a /locations/...,
    /branches/... o /ga/atlanta/... en vez de a la página principal."""
    u = str(url or "")
    p = urlparse(u if re.match(r"^https?://", u, re.I) else "http://" + u)
    seg = [x for x in p.path.lower().split("/") if x]
    if any("location" in x or x in ("branches", "offices") for x in seg):
        return True
    ambiguos = {"in", "me", "or", "de", "hi", "ok", "id", "oh", "la", "co", "pa", "ma", "al"}
    comunes = {"about", "contact", "services", "service", "blog", "home", "menu", "team", "news"}
    return (len(seg) >= 2 and seg[0] in ESTADOS_US - ambiguos
            and bool(re.fullmatch(r"[a-z-]{3,}", seg[1])) and seg[1] not in comunes)


# ---------------------------------------------------------------------------
# Métricas por negocio
# ---------------------------------------------------------------------------
def metricas_resenas(resenas, ahora):
    """Mide la actividad de respuesta sobre las reseñas más nuevas bajadas."""
    rs = []
    for r in resenas or []:
        origen = str(r.get("reviewOrigin") or "Google").lower()
        if origen != "google":
            continue  # solo se pueden responder las reseñas de Google
        d = fecha(r.get("publishedAtDate"))
        if not d:
            continue
        resp = bool(str(r.get("responseFromOwnerText") or "").strip())
        rs.append({
            "fecha": d,
            "estrellas": r.get("stars"),
            "respondida": resp,
            "fecha_resp": fecha(r.get("responseFromOwnerDate")) if resp else None,
            "texto": str(r.get("text") or "").strip(),
        })
    rs.sort(key=lambda x: x["fecha"], reverse=True)

    n = len(rs)
    m = {"n_muestra": n}
    if n == 0:
        m.update(respondidas=0, tasa_respuesta=None, sin_resp_reciente=0, sin_resp_total=0,
                 negativa_sin_resp=False, negativa_fecha=None, negativa_estrellas=None,
                 negativa_texto="", ultima_resena=None, dias_ultima_resena=None,
                 ultima_respuesta=None, dejo_de_responder=False, resenas_por_mes=0.0)
        return m

    resp = [x for x in rs if x["respondida"]]
    m["respondidas"] = len(resp)
    m["tasa_respuesta"] = round(len(resp) / n, 3) if n >= C.MIN_RESENAS_MUESTRA else None
    m["sin_resp_total"] = n - len(resp)
    m["sin_resp_reciente"] = sum(1 for x in rs if not x["respondida"]
                                 and (ahora - x["fecha"]).days <= C.DIAS_RECIENTE)

    neg = [x for x in rs if not x["respondida"] and x["estrellas"] is not None
           and x["estrellas"] <= 2 and (ahora - x["fecha"]).days <= C.DIAS_NEGATIVA]
    m["negativa_sin_resp"] = bool(neg)
    m["negativa_fecha"] = neg[0]["fecha"].date().isoformat() if neg else None
    m["negativa_estrellas"] = neg[0]["estrellas"] if neg else None
    m["negativa_texto"] = neg[0]["texto"][:1000] if neg else ""

    m["ultima_resena"] = rs[0]["fecha"].date().isoformat()
    m["dias_ultima_resena"] = max(0, (ahora - rs[0]["fecha"]).days)
    fechas_resp = [x["fecha_resp"] or x["fecha"] for x in resp]
    ultima_resp = max(fechas_resp) if fechas_resp else None
    m["ultima_respuesta"] = ultima_resp.date().isoformat() if ultima_resp else None
    # Respondía antes y dejó de hacerlo: la reseña más nueva no tiene respuesta
    # y llegó después de la última respuesta del dueño.
    m["dejo_de_responder"] = bool(resp) and not rs[0]["respondida"] and rs[0]["fecha"] > ultima_resp

    # Ritmo: cuántas reseñas por mes llegan, medido sobre el período que cubre la muestra.
    dias = max((ahora - rs[-1]["fecha"]).days, 1)
    m["resenas_por_mes"] = round(n / dias * 30, 2)
    return m


def puntaje(m, lugar):
    """Puntaje de 0 a 10 del negocio como prospecto, con el porqué."""
    p, porque = 0, []
    sr = m["sin_resp_reciente"]
    if sr >= 4:
        p += 4
    elif sr >= 2:
        p += 3
    elif sr == 1:
        p += 2
    if sr:
        porque.append(f"{sr} sin responder en {C.DIAS_RECIENTE} días")
    if m["negativa_sin_resp"]:
        p += 2
        porque.append(f"negativa de {m['negativa_estrellas']} estrellas sin responder")
    rpm = m["resenas_por_mes"]
    if rpm >= 3:
        p += 2
    elif rpm >= C.MIN_RESENAS_MES:
        p += 1
    porque.append(f"{rpm:g} reseñas por mes")
    rating = lugar.get("totalScore")
    if rating is not None and rating < 4.5:
        p += 1
        porque.append(f"rating {rating:g}")
    if lugar.get("isAdvertisement"):
        p += 1
        porque.append("paga anuncios en Google")
    return min(p, 10), " · ".join(porque)


# ---------------------------------------------------------------------------
# Del dato crudo a la tabla de negocios
# ---------------------------------------------------------------------------
def construir_negocios(crudo, emails=None, con_lugar=False):
    """crudo: {ciudad: bloque} o lista de (ciudad, bloque); bloque = {"fecha": iso, "items": [...], "zona": opcional}.
    Devuelve una fila por negocio y rubro. Con con_lugar=True deja el dato crudo en "_lugar"."""
    emails = emails or {}
    por_busqueda = {norm(r["busqueda"]): k for k, r in C.RUBROS.items()}
    bloques = crudo.items() if isinstance(crudo, dict) else crudo

    filas, vistos = [], set()
    for ciudad, bloque in bloques:
        ahora = fecha(bloque.get("fecha")) or datetime.now(timezone.utc)
        zona = bloque.get("zona") or ""
        for lugar in bloque.get("items", []):
            rubro = por_busqueda.get(norm(lugar.get("searchString")))
            if not rubro:
                continue
            pid = lugar.get("placeId") or lugar.get("url") or lugar.get("title")
            clave = (rubro, pid)
            if clave in vistos:
                continue
            vistos.add(clave)
            tipo_web, dominio = analizar_web(lugar.get("website"))
            filas.append({"_lugar": lugar, "_ahora": ahora, "ciudad": ciudad, "zona": zona, "rubro": rubro,
                          "place_id": pid, "tipo_web": tipo_web, "dominio": dominio})

    # Cadenas: dominio compartido en ciudades distintas o por 3+ negocios;
    # mismo nombre en ciudades distintas; o marca conocida.
    dom_lugares, dom_ciudades = defaultdict(set), defaultdict(set)
    nom_ciudades = defaultdict(set)
    for f in filas:
        if f["dominio"]:
            dom_lugares[f["dominio"]].add(f["place_id"])
            dom_ciudades[f["dominio"]].add(f["ciudad"])
        nom_ciudades[norm(f["_lugar"].get("title"))].add(f["ciudad"])

    salida = []
    for f in filas:
        l, ahora = f.pop("_lugar"), f.pop("_ahora")
        if con_lugar:
            f["_lugar"], f["_ahora"] = l, ahora
        motivo = None
        d = f["dominio"]
        if d and (len(dom_ciudades[d]) >= 2 or len(dom_lugares[d]) >= 3):
            motivo = f"web compartida ({d})"
        elif len(nom_ciudades[norm(l.get("title"))]) >= 2:
            motivo = "mismo nombre en varias ciudades"
        elif f["tipo_web"] == "propia" and web_de_sucursales(l.get("website")):
            motivo = "web de una empresa con sucursales"
        else:
            marca = es_marca_cadena(l.get("title"), d)
            if marca:
                motivo = f"marca conocida ({marca})"

        cerrado = bool(l.get("permanentlyClosed") or l.get("temporarilyClosed"))
        cat_ok = categoria_valida(l, f["rubro"])
        reclamado = not bool(l.get("claimThisBusiness"))
        m = metricas_resenas(l.get("reviews"), ahora)
        p, porque = puntaje(m, l)

        valido = cat_ok and not cerrado
        independiente = valido and motivo is None
        calificado = (independiente and reclamado and m["resenas_por_mes"] >= C.MIN_RESENAS_MES
                      and (m["sin_resp_reciente"] >= C.SIN_RESP_MIN or m["negativa_sin_resp"]))

        descarte = []
        if not cat_ok:
            descarte.append("otra categoría")
        if cerrado:
            descarte.append("cerrado")
        if motivo:
            descarte.append("cadena: " + motivo)
        if valido and not reclamado:
            descarte.append("perfil sin reclamar")

        mail = emails.get(d) if d else None
        f.update({
            "rubro_nombre": C.RUBROS[f["rubro"]]["nombre"],
            "ciudad_nombre": C.CIUDADES.get(f["ciudad"], {}).get("nombre", f["ciudad"]),
            "nombre": l.get("title"),
            "categoria": l.get("categoryName"),
            "posicion_maps": l.get("rank"),
            "direccion": l.get("address"),
            "telefono": l.get("phone"),
            "web": l.get("website"),
            "email": (mail or {}).get("email") if isinstance(mail, dict) else None,
            "maps": l.get("url"),
            "rating": l.get("totalScore"),
            "resenas_totales": l.get("reviewsCount") or 0,
            "paga_anuncios": bool(l.get("isAdvertisement")),
            "cerrado": cerrado,
            "categoria_ok": cat_ok,
            "cadena": motivo is not None,
            "motivo_cadena": motivo,
            "reclamado": reclamado,
            "valido": valido,
            "independiente": independiente,
            "prospecto_calificado": calificado,
            "puntaje": p if independiente and reclamado else 0,
            "porque": porque,
            "descarte": "; ".join(descarte),
            **m,
        })
        salida.append(f)
    return salida


# ---------------------------------------------------------------------------
# Resúmenes por grupo (rubro, ciudad, rubro x ciudad)
# ---------------------------------------------------------------------------
def resumir(negocios, claves, con_emails=False):
    grupos = defaultdict(list)
    for n in negocios:
        grupos[tuple(n[k] for k in claves)].append(n)

    filas = []
    for g, ns in grupos.items():
        validos = [n for n in ns if n["valido"]]
        indep = [n for n in validos if n["independiente"]]
        recl = [n for n in indep if n["reclamado"]]
        medibles = [n for n in recl if n["tasa_respuesta"] is not None]
        con_web = [n for n in indep if n["tipo_web"] == "propia"]
        calif = [n for n in indep if n["prospecto_calificado"]]

        fila = {k: v for k, v in zip(claves, g)}
        if "rubro" in claves:
            fila["rubro_nombre"] = C.RUBROS[fila["rubro"]]["nombre"]
            fila["ticket"] = C.RUBROS[fila["rubro"]]["ticket"]
        if "ciudad" in claves:
            fila["ciudad_nombre"] = C.CIUDADES.get(fila["ciudad"], {}).get("nombre", fila["ciudad"])
        fila.update({
            "encontrados": len(ns),
            "otra_categoria": sum(1 for n in ns if not n["categoria_ok"]),
            "cerrados": sum(1 for n in ns if n["categoria_ok"] and n["cerrado"]),
            "validos": len(validos),
            "pct_cadenas": pct(len(validos) - len(indep), len(validos)),
            "independientes": len(indep),
            "pct_sin_reclamar": pct(len(indep) - len(recl), len(indep)),
            "medibles": len(medibles),
            # Respuesta
            "pct_respuesta_mediana": redondo(100 * mediana([n["tasa_respuesta"] for n in medibles]), 1) if medibles else None,
            "pct_nunca_responde": pct(sum(1 for n in medibles if n["respondidas"] == 0), len(medibles)),
            "pct_sin_resp_reciente": pct(sum(1 for n in recl if n["sin_resp_reciente"] >= 1), len(recl)),
            "pct_negativa_sin_resp": pct(sum(1 for n in recl if n["negativa_sin_resp"]), len(recl)),
            "pct_dejo_de_responder": pct(sum(1 for n in medibles if n["dejo_de_responder"]), len(medibles)),
            # Volumen y reputación
            "resenas_mes_mediana": redondo(mediana([n["resenas_por_mes"] for n in recl])),
            "resenas_totales_mediana": mediana([n["resenas_totales"] for n in indep]),
            "rating_mediano": mediana([n["rating"] for n in indep]),
            "pct_rating_bajo_4_5": pct(sum(1 for n in indep if n["rating"] is not None and n["rating"] < 4.5),
                                       sum(1 for n in indep if n["rating"] is not None)),
            "pct_pocas_resenas": pct(sum(1 for n in indep if n["resenas_totales"] < C.POCAS_RESENAS), len(indep)),
            # Contacto y presupuesto
            "pct_con_web": pct(len(con_web), len(indep)),
            "pct_paga_anuncios": pct(sum(1 for n in indep if n["paga_anuncios"]), len(indep)),
            # Resultado
            "prospectos_calificados": len(calif),
            "pct_calificados": pct(len(calif), len(indep)),
            "puntaje_medio_calificados": redondo(statistics.mean([n["puntaje"] for n in calif]), 1) if calif else None,
        })
        if con_emails:
            fila["pct_web_con_email"] = pct(sum(1 for n in con_web if n["email"]), len(con_web))
            fila["pct_calificados_con_email"] = pct(sum(1 for n in calif if n["email"]), len(calif))
        filas.append(fila)

    filas.sort(key=lambda f: (-(f["pct_calificados"] or 0), -(f["resenas_mes_mediana"] or 0)))
    return filas
