"""Lee la bandeja de la casilla de envío y marca solo respuestas, bajas y rebotes en el registro.

Lo usa enviar.py antes de mandar cada tanda (cada 15 minutos en GitHub), así nadie recibe
un mail después de haber respondido, pedido la baja o rebotado.

Cómo clasifica cada mail nuevo de la bandeja:
- Rebote (mailer-daemon, "Delivery Status Notification", "Undeliverable"...): marca "rebotó" al
  destinatario que rebotó. Los avisos de demora ("Delay", "will retry") se ignoran.
- Respuesta automática (fuera de oficina, autoresponder): se ignora.
- Pedido de baja ("no", "unsubscribe", "remove me", "not interested", "stop"...): marca "baja"
  (bloquea a todo el dominio de la empresa).
- Cualquier otra respuesta de un prospecto (o de alguien de su misma empresa): marca "respondió".
En la duda, siempre para el lado seguro: una respuesta que no se entiende cuenta como respondida
(no recibe más seguimientos). Nunca se pasa de "baja" o "rebotó" a otro estado.
"""

import base64
import re
from html import unescape
from email.utils import getaddresses, parseaddr

import campana as K

GUARDAR_IDS = 3000
BUSQUEDA = "in:inbox -from:me newer_than:4d"

REBOTE_REMITENTE = re.compile(r"mailer-daemon|postmaster|mail delivery (sub)?system", re.I)
REBOTE_ASUNTO = re.compile(r"delivery status notification|undeliverable|undelivered|mail delivery failed|"
                           r"returned mail|failure notice|delivery (has )?failed|could not be delivered|"
                           r"address not found|message not delivered", re.I)
DEMORA = re.compile(r"\(delay\)|delayed|will (keep trying|retry)|has not yet been delivered", re.I)
AUTO_ASUNTO = re.compile(r"automatic reply|auto[- ]?reply|autoreply|auto[- ]?response|out of (the )?office|"
                         r"^\s*auto:|away from (the )?office|on vacation|we('ve| have) received your", re.I)
BAJA_TEXTO = re.compile(r"unsubscribe|remove (me|us|my|our)|take (me|us) off|stop (e-?mailing|sending|contacting)|"
                        r"do ?n[o']t (e-?mail|contact|send)|do not (e-?mail|contact|send)|no more e-?mails|"
                        r"not interested|no,? thanks?( you)?\b|please stop|opt[- ]?out", re.I)
BAJA_SOLO = re.compile(r"^\W*(no|nope|stop|no gracias|basta|baja)\W*$", re.I)
CORTE_CITA = re.compile(r"^\s*(on .{3,200}wrote:|-{2,}\s*original message|from:\s|sent from my|el .{3,200}escribió:)",
                        re.I | re.M)
EMAIL = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
ORDEN = {"respondió": 1, "baja": 2, "rebotó": 2}


# ---------------------------------------------------------------------------
# Lectura del mail
# ---------------------------------------------------------------------------
def _decodificar(data):
    try:
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        return ""


def texto_de(payload, preferir_plano=False):
    """Todo el texto legible del mail (partes text/* y message/*), sin HTML.
    Con preferir_plano, si hay versión de texto plano se usa solo esa (sin la copia en HTML)."""
    partes, pila = [], [payload or {}]
    while pila:
        p = pila.pop()
        pila.extend(reversed(p.get("parts") or []))
        tipo = (p.get("mimeType") or "").lower()
        data = (p.get("body") or {}).get("data")
        if data and (tipo.startswith("text/") or tipo.startswith("message/")):
            t = _decodificar(data)
            if tipo == "text/html":
                t = unescape(re.sub(r"<br\s*/?>", "\n", t, flags=re.I))
                t = re.sub(r"<[^>]+>", " ", t)
            partes.append((tipo, t))
    if preferir_plano and any(t == "text/plain" for t, _ in partes):
        partes = [x for x in partes if x[0] == "text/plain"]
    return "\n".join(t for _, t in partes)


def respuesta_nueva(texto):
    """Lo que escribió la persona, sin el mail citado de abajo."""
    lineas = [l for l in texto.splitlines() if not l.lstrip().startswith(">")]
    t = "\n".join(lineas)
    m = CORTE_CITA.search(t)
    return (t[:m.start()] if m else t).strip()


def cabeceras(msg):
    return {h["name"].lower(): h["value"] for h in (msg.get("payload") or {}).get("headers", [])}


# ---------------------------------------------------------------------------
# Clasificación
# ---------------------------------------------------------------------------
def es_automatica(cab, asunto):
    auto = cab.get("auto-submitted", "no").strip().lower()
    if auto and auto != "no":
        return True
    if any(k in cab for k in ("x-autoreply", "x-autorespond", "x-autoresponse")):
        return True
    if cab.get("precedence", "").strip().lower() in ("auto_reply", "bulk", "junk", "list"):
        return True
    return bool(AUTO_ASUNTO.search(asunto))


def clasificar(msg, registro):
    """(estado, [mails del registro], resumen) o (None, [], motivo) si no hay nada que marcar."""
    cab = cabeceras(msg)
    asunto = cab.get("subject", "")
    remitente = parseaddr(cab.get("from", ""))[1].strip().lower()
    nombre_rem = cab.get("from", "")
    texto = texto_de(msg.get("payload")) or msg.get("snippet", "")

    if REBOTE_REMITENTE.search(remitente) or REBOTE_REMITENTE.search(nombre_rem) or REBOTE_ASUNTO.search(asunto):
        if DEMORA.search(asunto) or (DEMORA.search(texto) and not re.search(r"permanent|failed", texto, re.I)):
            return None, [], "aviso de demora (no es rebote)"
        fallidos = [e.strip().lower() for _, e in getaddresses([cab.get("x-failed-recipients", "")]) if e]
        fallidos += [e.lower() for e in EMAIL.findall(texto)]
        quienes = sorted({e for e in fallidos if e in registro})
        if not quienes:
            return None, [], f"rebote sin destinatario del registro ({asunto[:60]})"
        return "rebotó", quienes, "rebote"

    quienes = buscar_prospecto(remitente, registro)
    if not quienes:
        return None, [], "no es de un prospecto"
    if es_automatica(cab, asunto):
        return None, [], f"respuesta automática de {remitente}"
    nuevo = respuesta_nueva(texto)
    if BAJA_SOLO.match(nuevo) or BAJA_TEXTO.search(nuevo) or BAJA_TEXTO.search(asunto):
        return "baja", quienes, nuevo[:120]
    return "respondió", quienes, nuevo[:120]


def buscar_prospecto(remitente, registro):
    """El prospecto que respondió: por su mail, o por el dominio de su empresa (otra persona del negocio)."""
    if not remitente:
        return []
    if remitente in registro:
        return [remitente]
    de = K.dominio_empresa(remitente)
    if not de:
        return []
    return sorted(e for e in registro if K.dominio_empresa(e) == de)


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------
def marcar(registro, bajas, email, estado, dia, extra=()):
    """Aplica la marca si sube de nivel (respondió < baja/rebotó). Devuelve True si cambió algo."""
    cambio = False
    if estado == "baja":
        for e in (email, *extra):
            if e and e not in bajas:
                bajas.append(e)
                cambio = True
    r = registro.get(email)
    if not r:
        return cambio
    actual = r.get("estado")
    if ORDEN.get(actual, 0) >= ORDEN[estado]:
        return cambio
    r.pop("armado", None)                       # si tenía un mail para hoy, ya no sale
    r["estado"] = estado
    r.setdefault("fechas", {})[estado] = dia
    return True


def estado_bandeja():
    """campana/bandeja.json: ids de los mails ya revisados (para no procesarlos dos veces)."""
    return K.DIR / "bandeja.json"


def leer_vistos():
    return list(K.leer_estricto(estado_bandeja(), {}, dict).get("vistos", []))


def guardar_vistos(vistos):
    K.guardar_json(estado_bandeja(), {"vistos": vistos[-GUARDAR_IDS:]})


def revisar(gmail, registro, bajas, dia):
    """Lee los mails nuevos y aplica las marcas en registro y bajas (en memoria).
    Devuelve (marcas [(email, estado, remitente, resumen)], ids nuevos revisados)."""
    vistos = set(leer_vistos())
    nuevos = [i for i in gmail.ids_bandeja(BUSQUEDA) if i not in vistos]
    marcas = []
    for mid in nuevos:
        msg = gmail.mensaje(mid)
        estado, quienes, resumen = clasificar(msg, registro)
        remitente = parseaddr(cabeceras(msg).get("from", ""))[1].strip().lower()
        if not estado:
            if resumen != "no es de un prospecto":
                print(f"  bandeja: {resumen}")
            continue
        for e in quienes:
            extra = [remitente] if estado == "baja" and remitente != e else []
            if marcar(registro, bajas, e, estado, dia, extra):
                marcas.append((e, estado, remitente, resumen))
                print(f"  MARCADO  {estado:<10} {e} ({registro[e].get('negocio', '')}): {resumen!r}")
    return marcas, nuevos
