"""Controles de la campaña automática: calidad de los borradores, freno de emergencia,
alertas, métricas y registro diario.

- Calidad: antes de mandar, cada borrador se revisa con reglas fijas (firma y baja de CAN-SPAM,
  precio, sin links, nombre del negocio, asunto, sin restos de plantilla). Si falla, no sale.
- Freno: con demasiados rebotes en los últimos primeros mails, o demasiadas bajas en un día,
  se frenan los primeros mails nuevos (los seguimientos siguen) hasta que Lucas lo destrabe:
  py campana.py destrabar
- Métricas (campana/metricas.json) y registro diario (campana/diario.json): los leen las
  tareas de Claude (resumen de la mañana, semanal y la revisión de resultados).
"""

import json
import re
from datetime import date, datetime, timedelta, timezone

import config as C
import campana as K

DIAS_DIARIO = 120


def ruta(nombre):
    """Archivos en la carpeta de la campaña (se calcula en el momento: los tests la cambian)."""
    return K.DIR / nombre


# ---------------------------------------------------------------------------
# Calidad de los borradores
# ---------------------------------------------------------------------------
CORTE_CITA = re.compile(r"^\s*on\s[\s\S]{3,250}?wrote:|^\s*-{2,}\s*original message|^\s*el\s[\s\S]{3,250}?escribió:",
                        re.I | re.M)
EMAIL = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
LINK = re.compile(r"https?://\S+|www\.\S+|\b[a-z0-9-]+\.(?:com|net|org|io|co|us|ar|biz|info|app|site)\b", re.I)
RESTO_PLANTILLA = re.compile(r"\[[^\]\n]{1,40}\]|\{\{|\}\}")
BAJA_FIRMA = re.compile(r"reply\s+[\"“”']?no[\"“”']?\s+and\s+i\s+won['’]t\s+email\s+you\s+again", re.I)
PLATA = re.compile(r"\$\s?(\d+(?:[.,]\d+)?)")
# Suenan a plantilla: si aparecen, el borrador no sale (reglas de plantillas.md del 22/11/2026).
FRASES_GASTADAS = ("didn't get buried", "thank you for the kind words", "my name is lucas",
                   "just started a small business", "your feedback is important")


def parte_nueva(texto):
    """El texto que escribió Lucas, sin el mail citado de abajo (en los seguimientos)."""
    lineas = [l for l in (texto or "").splitlines() if not l.lstrip().startswith(">")]
    t = "\n".join(lineas)
    m = CORTE_CITA.search(t)
    return (t[:m.start()] if m else t).strip()


def descuento(precio):
    return 29 if int(precio) <= 59 else 49


def revisar_borrador(texto, asunto, r, tipo):
    """Lista de problemas del borrador (vacía si está bien)."""
    problemas = []
    nuevo = parte_nueva(texto)
    plano = re.sub(r"\s+", " ", nuevo).lower()           # Gmail corta las líneas largas: se unen
    if not 250 <= len(nuevo) <= 4000:
        problemas.append(f"largo raro ({len(nuevo)} caracteres)")
    for pedazo, nombre in (("lucas pesqueira", "firma"), ("tinko projects", "firma"),
                           ("monseñor piaggio 55", "dirección postal")):
        if pedazo not in plano:
            problemas.append(f"falta la {nombre} ({pedazo})")
    if not BAJA_FIRMA.search(nuevo):
        problemas.append('falta la línea de baja (Reply "no" and I won\'t email you again)')
    precio = int(r.get("precio") or 0)
    montos = {int(float(m.replace(",", "."))) for m in PLATA.findall(nuevo)}
    # Plantillas del 22/11/2026: el seguimiento 1 ya no lleva precio (si lo lleva, tiene que ser el justo).
    permitidos = {precio, descuento(precio)} if tipo == "seguimiento 2" else {precio}
    if precio not in montos and tipo not in ("seguimiento 1", "seguimiento 3"):
        problemas.append(f"no aparece el precio (${precio})")
    if tipo == "seguimiento 2" and descuento(precio) not in montos:
        problemas.append(f"no aparece el descuento (${descuento(precio)})")
    if montos - permitidos:
        problemas.append(f"montos que no corresponden: {sorted(montos - permitidos)}")
    links = [l for l in LINK.findall(EMAIL.sub(" ", nuevo))]
    if tipo == "seguimiento 2":
        links = [l for l in links if "tinkoprojects.com" not in l.lower()]
    if links:
        problemas.append(f"tiene links: {links[:3]}")
    if RESTO_PLANTILLA.search(nuevo):
        problemas.append(f"quedó un resto de plantilla: {RESTO_PLANTILLA.search(nuevo).group(0)}")
    negocio = re.sub(r"\s+", " ", str(r.get("negocio") or "")).strip()
    # El registro no guarda negocio_corto: se calcula igual que en la tanda (sino un "Hi Shannon team" no pasa).
    corto = re.sub(r"\s+", " ", str(r.get("negocio_corto") or K.nombre_corto(negocio))).strip() or negocio
    if tipo in ("primer mail", "seguimiento 2", "seguimiento 3") and negocio.lower() not in plano and corto.lower() not in plano:
        problemas.append(f"no menciona al negocio ({corto})")
    if tipo == "primer mail" and "free" not in plano:
        problemas.append("falta la prueba gratis (free) en el primer mail")
    gastadas = [f for f in FRASES_GASTADAS if f in plano]
    if gastadas:
        problemas.append(f"frases gastadas: {gastadas}")
    norm = lambda s: re.sub(r"^\s*(re|fwd?):\s*", "", s or "", flags=re.I).strip().lower()
    esperado = f"{negocio}'s Google reviews" if tipo == "primer mail" else r.get("asunto", "")
    if norm(asunto) != norm(esperado):
        problemas.append(f"asunto distinto: '{asunto}' (tendría que ser '{esperado}')")
    return problemas


# ---------------------------------------------------------------------------
# Freno de emergencia
# ---------------------------------------------------------------------------
def leer_freno():
    return K.leer_estricto(ruta("freno.json"), {}, dict)


def freno_activo():
    return bool(leer_freno().get("activo"))


def evaluar_freno(registro, dia):
    """Motivo para frenar los primeros mails, o None. Solo cuenta lo enviado desde que arrancó
    el freno automático (o desde la última vez que se destrabó)."""
    f = leer_freno()
    desde = max(C.FRENO_DESDE, f.get("liberado", ""))
    max_reb, ventana = C.FRENO_REBOTES
    primeros = sorted(((r["fechas"]["enviado"], e) for e, r in registro.items()
                       if r.get("fechas", {}).get("enviado", "") >= desde), reverse=True)[:ventana]
    rebotes = [e for _, e in primeros if registro[e].get("estado") == "rebotó"]
    if len(rebotes) > max_reb:
        return f"{len(rebotes)} rebotes en los últimos {len(primeros)} primeros mails ({', '.join(rebotes)})"
    if dia > f.get("liberado", ""):
        bajas = [e for e, r in registro.items() if r.get("fechas", {}).get("baja") == dia]
        if len(bajas) > C.FRENO_BAJAS_DIA:
            return f"{len(bajas)} bajas hoy ({', '.join(bajas)})"
    return None


def activar_freno(registro, dia):
    """Si corresponde, activa el freno. Devuelve el motivo solo si se activó recién (para avisar una vez)."""
    if freno_activo():
        return None
    motivo = evaluar_freno(registro, dia)
    if motivo:
        f = leer_freno()
        f.update({"activo": True, "desde": dia, "motivo": motivo})
        K.guardar_json(ruta("freno.json"), f)
    return motivo


def destrabar(dia):
    f = leer_freno()
    if not f.get("activo"):
        print("El freno no está activo.")
        return False
    K.guardar_json(ruta("freno.json"), {"activo": False, "liberado": dia, "ultimo_motivo": f.get("motivo")})
    print(f"Freno destrabado ({f.get('motivo')}). Los rebotes y bajas anteriores ya no cuentan.")
    return True


# ---------------------------------------------------------------------------
# Registro diario
# ---------------------------------------------------------------------------
def leer_diario():
    return K.leer_estricto(ruta("diario.json"), {}, dict)


def anotar(dia, clave, valor, unico_por=None):
    """Agrega un evento al día. Con unico_por (campo), no repite el mismo valor."""
    d = leer_diario()
    lista = d.setdefault(dia, {}).setdefault(clave, [])
    if unico_por and any(x.get(unico_por) == valor.get(unico_por) for x in lista):
        return
    if valor in lista:
        return
    lista.append(valor)
    limite = (date.fromisoformat(dia) - timedelta(days=DIAS_DIARIO)).isoformat()
    K.guardar_json(ruta("diario.json"), {k: v for k, v in sorted(d.items()) if k >= limite})


def anotar_tanda(dia, resumen):
    d = leer_diario()
    d.setdefault(dia, {})["tanda"] = resumen
    K.guardar_json(ruta("diario.json"), d)


# ---------------------------------------------------------------------------
# Métricas y alertas
# ---------------------------------------------------------------------------
def _grupo():
    return {"contactados": 0, "respondieron": 0, "bajas": 0, "rebotes": 0, "secuencia_completa": 0}


def _tras(r):
    """Después de qué mail respondió."""
    f = r.get("fechas", {})
    resp = f.get("respondió")
    if not resp:
        return None
    for tipo in ("seguimiento 3", "seguimiento 2", "seguimiento 1"):
        if f.get(tipo) and f[tipo] <= resp:
            return f"tras {tipo}"
    return "tras primer mail"


def stock(registro, bajas, prospectos=None):
    """Prospectos de la lista (sin vencer) que todavía no se contactaron, por prioridad."""
    if prospectos is None and not K.PROSPECTOS.exists():
        return {}
    usados = set(registro) | {str(b).lower() for b in bajas}
    doms = K.dominios_bloqueados(bajas) | {K.dominio_empresa(e) for e in registro} - {""}
    out = {"A": 0, "B": 0, "C": 0}
    for p in (prospectos if prospectos is not None else K.cargar_prospectos()):
        e = p["email"].strip().lower()
        if e in usados or (K.dominio_empresa(e) and K.dominio_empresa(e) in doms):
            continue
        out[p.get("prioridad") or "C"] = out.get(p.get("prioridad") or "C", 0) + 1
    return out


def calcular(registro, bajas, dia):
    reg = {e: r for e, r in registro.items() if r.get("estado") not in ("armado", "descartado")
           and r.get("fechas", {}).get("enviado")}
    total = _grupo()
    grupos = {"rubro": {}, "ciudad": {}, "prioridad": {}}
    respuestas_por_mail = {}
    for e, r in reg.items():
        f = r.get("fechas", {})
        sumar = {"contactados": 1,
                 "respondieron": int("respondió" in f),
                 "bajas": int(r.get("estado") == "baja"),
                 "rebotes": int(r.get("estado") == "rebotó"),
                 "secuencia_completa": int("seguimiento 2" in f)}
        destinos = [total] + [grupos[c].setdefault(str(r.get(c) or "(sin dato)"), _grupo()) for c in grupos]
        for g in destinos:
            for k, v in sumar.items():
                g[k] += v
        t = _tras(r)
        if t:
            respuestas_por_mail[t] = respuestas_por_mail.get(t, 0) + 1
    for g in [total] + [x for c in grupos.values() for x in c.values()]:
        g["tasa_respuesta_%"] = round(100 * g["respondieron"] / g["contactados"], 1) if g["contactados"] else None
        g["tasa_rebote_%"] = round(100 * g["rebotes"] / g["contactados"], 1) if g["contactados"] else None
    st = stock(registro, bajas)
    return {"dia": dia, "total": total, **{f"por_{c}": v for c, v in grupos.items()},
            "respuestas_por_mail": respuestas_por_mail, "stock_sin_contactar": st,
            "alertas": alertas(st, dia), "freno": leer_freno()}


def alertas(st, dia):
    out = []
    ab = st.get("A", 0) + st.get("B", 0) if st else None
    if ab is not None and ab < C.ALERTA_STOCK_AB:
        out.append(f"Quedan {ab} prospectos A/B sin contactar: conviene buscar más (py prospectar.py buscar).")
    diario = leer_diario()
    tandas = [v["tanda"] for k, v in sorted(diario.items()) if "tanda" in v and k <= dia][-5:]
    if tandas:
        ultima = tandas[-1]
        libre = ultima.get("credito_libre")
        gastos = [t.get("gasto_estimado") for t in tandas if t.get("gasto_estimado")]
        por_dia = max(sum(gastos) / len(gastos), 0.5) if gastos else 1.0
        if libre is not None and libre < C.ALERTA_CREDITO_DIAS * por_dia:
            out.append(f"Al crédito de Apify le quedan USD {libre:.2f}: alcanza para ~{int(libre // por_dia)} tandas.")
        if ultima.get("cupo_nuevos", 0) >= C.ALERTA_TANDA_MIN and ultima.get("nuevos", 0) < C.ALERTA_TANDA_MIN:
            out.append(f"La última tanda ({ultima.get('fecha')}) salió con solo {ultima.get('nuevos')} primeros mails.")
    if freno_activo():
        f = leer_freno()
        out.insert(0, f"FRENO ACTIVO desde el {f.get('desde')}: {f.get('motivo')}. "
                      f"No salen primeros mails. Revisalo y destrabalo con: py campana.py destrabar")
    return out


def actualizar(registro, bajas, dia):
    """Recalcula las métricas y las guarda solo si cambiaron (para no hacer commits de más)."""
    nuevo = calcular(registro, bajas, dia)
    previo = K.leer_estricto(ruta("metricas.json"), {}, dict)
    sin_hora = {k: v for k, v in previo.items() if k != "actualizado"}
    if sin_hora == nuevo:
        return nuevo
    nuevo_con_hora = dict(nuevo, actualizado=datetime.now(timezone.utc).isoformat(timespec="minutes"))
    K.guardar_json(ruta("metricas.json"), nuevo_con_hora)
    return nuevo
