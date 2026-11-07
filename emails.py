"""Busca el mail público de cada negocio en su propia web (gratis, sin Apify).

Mira la página principal y hasta dos páginas de contacto. Sirve para medir qué
porcentaje de cada rubro se puede contactar por mail.
"""

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape
from urllib.parse import urljoin, urlparse

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
RE_MAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,24}")
RE_HREF = re.compile(r"""href\s*=\s*["']([^"'#]+)["']""", re.I)
RE_CF = re.compile(r"""data-cfemail\s*=\s*["']([0-9a-fA-F]+)["']""")
PALABRAS_CONTACTO = ("contact", "about", "get-in-touch", "reach-us", "location")
EXT_FALSAS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js", ".ico")
DOMINIOS_BASURA = (
    "example.com", "sentry.io", "wixpress.com", "sentry-next.wixpress.com", "domain.com",
    "email.com", "yourdomain.com", "yoursite.com", "godaddy.com", "squarespace.com",
    "schema.org", "w3.org", "wix.com", "mysite.com", "company.com", "test.com",
)
LOCALES_BASURA = ("user", "name", "your", "youremail", "email", "info@example", "username",
                  "johndoe", "john.doe", "firstname", "noreply", "no-reply", "donotreply")
GRATUITOS = ("gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "aol.com", "icloud.com",
             "live.com", "msn.com", "comcast.net", "att.net", "sbcglobal.net", "bellsouth.net")


def _cf(hexa):
    try:
        b = bytes.fromhex(hexa)
        return "".join(chr(x ^ b[0]) for x in b[1:])
    except ValueError:
        return ""


def extraer(html):
    html = unescape(html)
    encontrados = set(m.group(0) for m in RE_MAIL.finditer(html))
    encontrados |= {_cf(h) for h in RE_CF.findall(html)}
    limpios = set()
    for e in encontrados:
        e = e.strip(".-_").lower()
        if not e or "@" not in e:
            continue
        local, _, dom = e.partition("@")
        if e.endswith(EXT_FALSAS) or dom in DOMINIOS_BASURA or local in LOCALES_BASURA:
            continue
        if re.search(r"\d+x\d*$", dom) or len(local) > 40:
            continue  # nombres de imágenes tipo logo@2x.png
        limpios.add(e)
    return limpios


# Mails de áreas que no deciden la compra: se descartan.
ROLES_NO = ("accessibility", "ada", "privacy", "legal", "careers", "jobs", "hr", "recruiting",
            "abuse", "webmaster", "security", "compliance", "press", "media", "noreply",
            "no-reply", "donotreply", "unsubscribe", "postmaster")
# Mails de administración: solo si no hay otro.
ROLES_ULTIMO = ("ap", "ar", "billing", "accounting", "accounts", "invoices", "invoice",
                "payroll", "payments", "support", "events", "event", "catering", "reservations",
                "reservation", "leasing", "orders", "order", "giftcards")


def normalizar(m):
    """Arregla mails mal leídos de la web: espacios codificados (%20) y teléfonos pegados adelante."""
    from urllib.parse import unquote
    m = unquote(str(m or "")).strip().strip(".,;:<>\"'()[]").lower()
    if "@" not in m:
        return ""
    local, _, dom = m.partition("@")
    local = re.sub(r"^[\s\d().+-]{5,}", "", local).strip(".-_ ")   # 499-9324relocation -> relocation
    local = local.split()[-1] if local.split() else ""
    if not local or not re.fullmatch(r"[a-z0-9._%+-]+", local):
        return ""
    return f"{local}@{dom}"


def elegir(mails, dominio):
    """El mejor: del mismo dominio que la web, después uno gratuito, después cualquiera.
    Descarta mails de áreas que no compran y deja los de administración para el final."""
    local = lambda m: m.split("@")[0].lower()
    mails = sorted({normalizar(m) for m in (mails or [])} - {""})
    mails = [m for m in mails if local(m) not in ROLES_NO]
    if not mails:
        return None
    buenos = [m for m in mails if local(m) not in ROLES_ULTIMO]
    if buenos:
        mails = buenos
    def es_propio(m):
        dom = m.split("@")[1]
        return bool(dominio) and (dom == dominio or dom.endswith("." + dominio))

    propios = sorted(m for m in mails if es_propio(m))
    if propios:
        return propios[0]
    gratis = sorted(m for m in mails if m.split("@")[1] in GRATUITOS)
    return gratis[0] if gratis else sorted(mails)[0]


def _bajar(s, url):
    try:
        r = s.get(url, timeout=12, allow_redirects=True, stream=True)
        if r.status_code >= 400 or "html" not in r.headers.get("Content-Type", "html"):
            return None, url
        contenido = r.raw.read(2_000_000, decode_content=True)
        return contenido.decode(r.encoding or "utf-8", errors="ignore"), r.url
    except (requests.RequestException, OSError, ValueError):
        return None, url


HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def variantes(url):
    """La web tal cual, sin parámetros de seguimiento, con https/http y con/sin www."""
    u = url if re.match(r"^https?://", url, re.I) else "http://" + url
    p = urlparse(u)
    host = (p.hostname or "").lower()
    sin_www = host[4:] if host.startswith("www.") else host
    vistas, out = set(), []
    for v in [u, f"https://{host}{p.path or '/'}", f"https://{sin_www}/", f"https://www.{sin_www}/",
              f"http://{sin_www}/"]:
        if v not in vistas:
            vistas.add(v)
            out.append(v)
    return out


def buscar_en_web(url, dominio):
    s = requests.Session()
    s.headers.update(HEADERS)
    html, final = None, url
    for v in variantes(url):
        html, final = _bajar(s, v)
        if html is not None:
            break
    if html is None:
        return {"estado": "web caída o bloqueada", "email": None, "emails": []}
    mails = extraer(html)
    host = (urlparse(final).hostname or "").lower()
    candidatos = []
    for href in RE_HREF.findall(html):
        if href.lower().startswith("mailto:"):
            continue
        absoluta = urljoin(final, href)
        h = (urlparse(absoluta).hostname or "").lower()
        if h == host and any(p in absoluta.lower() for p in PALABRAS_CONTACTO) and absoluta not in candidatos:
            candidatos.append(absoluta)
    for extra in candidatos[:2]:
        h2, _ = _bajar(s, extra)
        if h2:
            mails |= extraer(h2)
    return {"estado": "ok", "email": elegir(mails, dominio), "emails": sorted(mails)[:10]}


def tiene_mx(dominio, sesion=None):
    """¿El dominio puede recibir mails? Consulta DNS por HTTPS. None si no se pudo saber."""
    s = sesion or requests
    for url in ("https://dns.google/resolve", "https://cloudflare-dns.com/dns-query"):
        try:
            r = s.get(url, params={"name": dominio, "type": "MX"},
                      headers={"accept": "application/dns-json"}, timeout=10)
            d = r.json()
        except (requests.RequestException, ValueError):
            continue
        if d.get("Status") == 3:  # el dominio no existe
            return False
        if d.get("Status") == 0:
            return any(a.get("type") == 15 for a in d.get("Answer", []))
    return None


def chequear_mx(dominios, previos=None, hilos=12):
    resultados = dict(previos or {})
    pendientes = [d for d in dominios if d not in resultados]
    with ThreadPoolExecutor(max_workers=hilos) as ex:
        for d, ok in zip(pendientes, ex.map(tiene_mx, pendientes)):
            if ok is not None:
                resultados[d] = ok
    return resultados


def buscar_todos(webs, previos=None, al_avanzar=None, hilos=12):
    """webs: {dominio: url}. Devuelve {dominio: resultado}. Saltea los ya revisados, salvo
    las webs que no cargaron: a esas les da un segundo intento."""
    resultados = dict(previos or {})
    pendientes = {d: u for d, u in webs.items()
                  if d not in resultados
                  or (resultados[d].get("estado") != "ok" and not resultados[d].get("reintento"))}
    reintentos = {d for d in pendientes if d in resultados}
    with ThreadPoolExecutor(max_workers=hilos) as ex:
        futuros = {ex.submit(buscar_en_web, u, d): d for d, u in pendientes.items()}
        for i, f in enumerate(as_completed(futuros), 1):
            d = futuros[f]
            try:
                resultados[d] = f.result()
            except Exception as e:  # una web rara no frena al resto
                resultados[d] = {"estado": f"error: {type(e).__name__}", "email": None, "emails": []}
            if d in reintentos:
                resultados[d]["reintento"] = True
            if al_avanzar:
                al_avanzar(i, len(pendientes))
    return resultados
