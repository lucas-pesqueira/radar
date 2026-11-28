"""Escribe los borradores de la tanda del día en Gmail (24/11/2026).

Reemplaza a la tarea programada de Claude de las 8:42, que dejó de poder crear borradores.
- Primer mail: el texto lo arma este script con la plantilla de campana/plantillas.md; las dos
  respuestas a reseñas las escribe la API de Claude (ANTHROPIC_API_KEY), con las reglas de la
  sección "Cómo escribir las respuestas" de plantillas.md.
- Seguimientos: no necesitan IA. Se arman con la plantilla y van como respuesta en el hilo.
- Cada borrador pasa por control.revisar_borrador antes de crearse: si no pasa, no se crea.
- Es idempotente: si ya hay un borrador para ese mail, no hace otro. Por eso corre después de la
  tanda (6:47) y otra vez en cada corrida del envío (plan B: reintenta lo que haya fallado).

Uso:
    py escribir.py            escribe los que falten de hoy
    py escribir.py --prueba   muestra los textos sin crear nada (sin IA: respuestas de ejemplo)
"""
import base64
import json
import os
import re
import sys
import time
from datetime import date, datetime
from email.mime.text import MIMEText
from email.utils import formatdate

import requests

import campana as K
import config as C
import control as X

API = "https://api.anthropic.com/v1/messages"
MESES = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
         "October", "November", "December")
FIRMA = ("Lucas\n\nLucas Pesqueira · Tinko Projects\n"
         "Monseñor Piaggio 55, Avellaneda (1870), Buenos Aires, Argentina · "
         "Reply \"no\" and I won't email you again.")
NEGATIVA = "People reading your reviews notice when a bad one goes unanswered."
RUBRO_TEXTO = {"Administradoras de alquileres": ("property management companies", "property managers"),
               "Mudanzas": ("local moving companies", "moving companies"),
               "Restaurantes independientes": ("local restaurants", "restaurants"),
               "Salones de uñas": ("local nail salons", "nail salons")}


class ErrorIA(Exception):
    pass


# ---------------------------------------------------------------------------
# Textos
# ---------------------------------------------------------------------------
def fecha_larga(iso):
    d = date.fromisoformat(str(iso)[:10])
    return f"{MESES[d.month - 1]} {d.day}"


def rubros(rubro):
    return RUBRO_TEXTO.get(rubro, ("local businesses", "local businesses"))


def saludo(item):
    return item.get("negocio_corto") or K.nombre_corto(item["negocio"])


def primer_mail(item, respuestas, hoy):
    """respuestas: [(reseña, texto de la respuesta)], en el orden en que se citan."""
    r1 = respuestas[0][0]
    autor, estrellas = (r1.get("autor") or "").strip(), int(r1.get("estrellas") or 5)
    cuando = "" if item.get("prioridad") == "C" else f" from {fecha_larga(r1['fecha'])}"
    sujeto = f"{autor}'s {estrellas}-star review{cuando}" if autor else f"A {estrellas}-star review{cuando}"
    sin, de = int(item.get("sin_responder") or 1), int(item.get("de_las_ultimas") or 5)
    if sin >= de:
        resto = f", and none of your {de} most recent reviews have a reply either."
    elif sin <= 1:
        resto = "."
    else:
        resto = f", and {sin} of your {de} most recent reviews are the same."
    p1 = f"{sujeto} is still waiting for a reply{resto}"
    if estrellas <= 3:
        p1 += " " + NEGATIVA
    if item.get("comp_responden") and item.get("comp_ejemplo"):
        p1 += (f" Meanwhile, {item['comp_responden']} of the {item.get('comp_de', 5)} {rubros(item['rubro'])[1]} "
               f"closest to you on Google Maps answer their reviews, including {item['comp_ejemplo']}.")
    una = len(respuestas) == 1
    p1 += " So I wrote a reply you can copy and paste:" if una else " So I wrote replies you can copy and paste:"
    citas = []
    for res, texto in respuestas:
        a = (res.get("autor") or "").strip()
        citas.append(f'To {a}: "{texto}"' if a else f'To the {int(res.get("estrellas") or 5)}-star review: "{texto}"')
    mas_nueva = max(date.fromisoformat(str(res["fecha"])[:10]) for res, _ in respuestas)
    dias = 30 if (hoy - mas_nueva).days <= 30 else 90
    tuyo = "It's yours either way, no strings attached." if una else "They're yours either way, no strings attached."
    oferta = (f"I'm Lucas, and I write review replies for {rubros(item['rubro'])[0]}. If you'd like, I'll reply "
              f"to all your unanswered reviews from the last {dias} days for free, and you approve each one "
              f"before it goes live. After that it's ${item['precio']}/month to keep up with every new review. "
              "No contract.")
    if item.get("en_espanol"):
        oferta += " I also reply in Spanish when a review comes in Spanish."
    cuerpo = "\n\n".join([f"Hi {saludo(item)} team,", p1, *citas, tuyo, oferta,
                          'Want me to do it? Just reply "yes".', FIRMA])
    return f"{item['negocio']}'s Google reviews", cuerpo


def seguimiento_1(nombres, dias=30):
    if not nombres:
        pregunta = "Did the replies I wrote for your reviews come in handy?"
    elif len(nombres) == 1:
        pregunta = f"Did the reply for {nombres[0]} come in handy?"
    else:
        pregunta = f"Did the replies for {nombres[0]} and {nombres[1]} come in handy?"
    return "\n\n".join(["Hi again,", pregunta,
                        "If someone else takes care of your Google profile, could you forward this to them? "
                        f"The offer stands: I'll reply to your unanswered reviews from the last {dias} days for "
                        "free, and nothing goes live without your OK.", FIRMA])


def seguimiento_2(item, hoy):
    precio = int(item["precio"])
    cierre = ("Thanks, and good luck with the holidays." if (hoy.month == 12 or (hoy.month == 11 and hoy.day >= 15)
                                                             or (hoy.month == 1 and hoy.day < 4))
              else "Thanks, and good luck with everything.")
    return "\n\n".join([
        f"Hi {saludo(item)} team,", "One more idea before I leave you alone.",
        "I'm just getting started (I'm based in Buenos Aires and work U.S. hours), so I'm looking for a few "
        f"local {rubros(item['rubro'])[1]} to work with in exchange for honest feedback. If you're one of them, "
        "the free month of replies still stands, and after that it's "
        f"${X.descuento(precio)}/month for your first 3 months instead of ${precio}.",
        "If now's not the right time, no worries. You can see more about me at tinkoprojects.com.",
        cierre, FIRMA])


def seguimiento_3(item):
    """El último toque (27/11/2026): corto, sin precio, fácil de contestar con una palabra."""
    return "\n\n".join([
        f"Hi {saludo(item)} team,",
        f"Should I close the file on the reviews for {saludo(item)}?",
        'If the timing is just wrong, reply "later" and I\'ll check back in a few months. '
        "If it's a no, no need to answer: this is my last email.", FIRMA])


def nombres_del_hilo(texto):
    """Nombres a los que se les escribió respuesta en el primer mail ("To Ray:", "To the 4-star review:")."""
    plano = re.sub(r"\s+", " ", texto or "")
    out = []
    for n in re.findall(r'To ([^:"]{1,40}): "', plano):
        n = n.strip()
        m = re.match(r"the (\d)-star review", n, re.I)
        out.append(f"your {m.group(1)}-star review" if m else n)
    return out[:2]


def dias_del_hilo(texto):
    return 90 if "last 90 days" in re.sub(r"\s+", " ", texto or "") else 30


# ---------------------------------------------------------------------------
# Respuestas con la API de Claude
# ---------------------------------------------------------------------------
def reglas_respuestas():
    """La sección de reglas de plantillas.md (una sola fuente de verdad)."""
    p = K.DIR / "plantillas.md"
    s = p.read_text(encoding="utf-8") if p.exists() else ""
    m = re.search(r"### Cómo escribir las respuestas a las reseñas(.*?)(?=\n### |\n## )", s, re.S)
    return m.group(1).strip() if m else ""


def pedir_respuestas(item, clave=None, sesion=None):
    """Le pide a Claude las respuestas. Devuelve [(reseña, texto)] sin las reseñas con acusaciones graves."""
    clave = clave or os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not clave:
        raise ErrorIA("falta ANTHROPIC_API_KEY")
    resenas = item.get("resenas") or []
    entrada = [{"n": i, "autor": r.get("autor") or "", "estrellas": r.get("estrellas"),
                "texto": (r.get("texto") or "")[:1500]} for i, r in enumerate(resenas)]
    sistema = (
        "You write replies to Google reviews on behalf of a small U.S. business owner. Follow these rules "
        "(written in Spanish for the team, but your replies are in the language of each review):\n\n"
        + reglas_respuestas() +
        "\n\nAlso: if a review contains a serious accusation (theft, discrimination, racism, health or safety, "
        "habitability such as rats or mold, violence, weapons, legal threats), do NOT reply to it: mark it as "
        "skipped. Return ONLY a JSON object, no other text: "
        '{"replies": [{"n": <index>, "reply": "<text>"}], "skipped": [{"n": <index>, "reason": "<short>"}]}')
    usuario = (f"Business: {item['negocio']} ({item.get('rubro')}, {item.get('ciudad')}).\n"
               f"Reviews:\n{json.dumps(entrada, ensure_ascii=False)}")
    s = sesion or requests.Session()
    ultimo = ""
    for intento in range(3):
        try:
            r = s.post(API, timeout=90, headers={"x-api-key": clave, "anthropic-version": "2023-06-01",
                                                 "content-type": "application/json"},
                       json={"model": C.MODELO_ESCRITURA, "max_tokens": 800, "system": sistema,
                             "messages": [{"role": "user", "content": usuario}]})
        except requests.RequestException as e:
            ultimo = str(e)
            time.sleep(5 * (intento + 1))
            continue
        if r.status_code in (429, 500, 502, 503, 529):
            ultimo = f"{r.status_code}"
            time.sleep(10 * (intento + 1))
            continue
        if r.status_code != 200:
            raise ErrorIA(f"la API respondió {r.status_code}: {r.text[:200]}")
        texto = "".join(b.get("text", "") for b in r.json().get("content", []))
        m = re.search(r"\{.*\}", texto, re.S)
        try:
            datos = json.loads(m.group(0)) if m else {}
        except json.JSONDecodeError:
            ultimo = "respuesta que no es JSON"
            continue
        saltear = {int(x.get("n", -1)) for x in datos.get("skipped", [])}
        out = []
        for x in datos.get("replies", []):
            n = int(x.get("n", -1))
            t = re.sub(r"\s+", " ", str(x.get("reply") or "")).strip().strip('"')
            if 0 <= n < len(resenas) and n not in saltear and t:
                out.append((resenas[n], t.replace('"', "'")))
        out.sort(key=lambda p: resenas.index(p[0]))
        return out[:2]
    raise ErrorIA(f"la API no respondió bien ({ultimo})")


# ---------------------------------------------------------------------------
# Gmail
# ---------------------------------------------------------------------------
def mime(para, asunto, cuerpo, en_respuesta_a=None):
    m = MIMEText(cuerpo, "plain", "utf-8")
    m["To"] = para
    m["Subject"] = asunto
    m["Date"] = formatdate(localtime=True)
    if en_respuesta_a:
        m["In-Reply-To"] = en_respuesta_a
        m["References"] = en_respuesta_a
    return base64.urlsafe_b64encode(m.as_bytes()).decode()


def crear_borrador(gmail, para, asunto, cuerpo, hilo=None, en_respuesta_a=None):
    msg = {"raw": mime(para, asunto, cuerpo, en_respuesta_a)}
    if hilo:
        msg["threadId"] = hilo
    return gmail._pedir("POST", "/drafts", json={"message": msg})["id"]


def hilo_enviado(gmail, email):
    """(threadId, Message-ID del último mail mandado, texto del primero) del hilo con ese mail, o None."""
    r = gmail._pedir("GET", "/messages", params={"q": f"in:sent to:{email}", "maxResults": 20})
    ids = [m["id"] for m in r.get("messages", [])]
    if not ids:
        return None
    mensajes = [gmail._pedir("GET", f"/messages/{i}", params={"format": "full"}) for i in ids]
    mensajes.sort(key=lambda m: int(m.get("internalDate", 0)))
    ultimo = mensajes[-1]
    cab = {h["name"].lower(): h["value"] for h in ultimo.get("payload", {}).get("headers", [])}
    import bandeja as B
    primero = B.texto_de(mensajes[0].get("payload"), preferir_plano=True)
    return ultimo.get("threadId"), cab.get("message-id"), primero


# ---------------------------------------------------------------------------
# Tanda
# ---------------------------------------------------------------------------
def items_de(dia):
    out = []
    for f in sorted(K.TANDAS.glob(f"tanda_{dia}*.json")):
        if f.name.endswith("_prueba.json"):
            continue
        out += json.loads(f.read_text(encoding="utf-8")).get("items", [])
    return out


def escribir(gmail=None, dia=None, prueba=False, ia=None):
    """Crea los borradores que falten. Devuelve (creados, salteados, problemas)."""
    dia = dia or K.hoy().isoformat()
    hoy = date.fromisoformat(dia)
    registro = K.leer_registro()
    existentes = gmail.borradores() if gmail else {}
    ia = ia or pedir_respuestas
    creados, salteados, problemas = [], [], []
    for it in items_de(dia):
        email = it["email"].strip().lower()
        r = registro.get(email, {})
        if (r.get("armado") or {}).get("fecha") != dia:
            continue                                   # ya mandado o de otra tanda
        if r.get("estado") in ("respondió", "baja", "rebotó", "descartado"):
            salteados.append((email, f"estado {r.get('estado')}"))
            continue
        if existentes.get(email):
            continue
        tipo = it["tipo"]
        try:
            hilo = msgid = None
            if tipo == "primer mail":
                resp = ia(it)
                if not resp:
                    salteados.append((email, "todas las reseñas tienen acusaciones graves"))
                    continue
                asunto, cuerpo = primer_mail(it, resp, hoy)
            else:
                asunto = it.get("asunto") or r.get("asunto") or f"{it['negocio']}'s Google reviews"
                h = hilo_enviado(gmail, email) if gmail else ("", "", "")
                if not h:
                    problemas.append((email, "no encontré el hilo del primer mail"))
                    continue
                hilo, msgid, primero = h
                if tipo == "seguimiento 1":
                    cuerpo = seguimiento_1(nombres_del_hilo(primero), dias_del_hilo(primero))
                elif tipo == "seguimiento 2":
                    cuerpo = seguimiento_2(it, hoy)
                else:
                    cuerpo = seguimiento_3(it)
            fallas = X.revisar_borrador(cuerpo, asunto, {**r, **it}, tipo)
            if fallas:
                problemas.append((email, "no pasa el control: " + "; ".join(fallas)))
                continue
            if prueba or not gmail:
                print(f"\n===== {tipo} · {email} · {asunto}\n{cuerpo}")
            else:
                crear_borrador(gmail, email, asunto, cuerpo, hilo, msgid)
            creados.append((it.get("hora_art", ""), tipo, it["negocio"], email))
        except ErrorIA as e:
            problemas.append((email, f"IA: {e}"))
        except Exception as e:  # un ítem raro no frena al resto
            problemas.append((email, f"{type(e).__name__}: {str(e)[:150]}"))
    return creados, salteados, problemas


def main():
    prueba = "--prueba" in sys.argv
    gmail = None
    ia = None
    if prueba:
        ia = lambda it: [(x, "Hi, thank you for the review.") for x in (it.get("resenas") or [])[:2]]
    else:
        import enviar as E
        gmail = E.Gmail()
    creados, salteados, problemas = escribir(gmail, prueba=prueba, ia=ia)
    print(f"Borradores {'(prueba) ' if prueba else ''}creados: {len(creados)}")
    for h, t, n, e in sorted(creados):
        print(f"  {h}  {t:14} {n} <{e}>")
    for e, m in salteados:
        print(f"  SALTEADO  {e}: {m}")
    for e, m in problemas:
        print(f"  PROBLEMA  {e}: {m}")
    if problemas and not prueba:
        sys.exit(f"{len(problemas)} borradores no se pudieron escribir (se reintentan en el próximo envío).")


if __name__ == "__main__":
    main()
