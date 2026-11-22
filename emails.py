"""Busca el mail público de cada negocio en su propia web (gratis, sin Apify).

Mira la página principal y hasta dos páginas de contacto. Sirve para medir qué
porcentaje de cada rubro se puede contactar por mail.
"""

import collections
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape
from urllib.parse import urljoin, urlparse

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
RE_MAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,24}")
RE_HREF = re.compile(r"""href\s*=\s*["']([^"'#]+)["']""", re.I)
RE_CF = re.compile(r"""data-cfemail\s*=\s*["']([0-9a-fA-F]+)["']|/cdn-cgi/l/email-protection#([0-9a-fA-F]+)""")
RE_MAILTO = re.compile(r"""mailto:([^"'?>\s]+)""", re.I)
# "info [at] negocio [dot] com", "info(at)negocio(dot)com", "info {at} negocio.com": mails escritos para esquivar robots.
RE_OCULTO = re.compile(r"([a-z0-9._%+-]+)\s*[\[\(\{]\s*(?:at|arroba|@)\s*[\]\)\}]\s*"
                       r"([a-z0-9-]+(?:\s*(?:[\[\(\{]\s*(?:dot|punto|\.)\s*[\]\)\}]|\.)\s*[a-z0-9-]+)+)", re.I)
try:
    import gender_guesser.detector  # noqa: F401  (para el nombre del dueño)
    _HAY_NOMBRES = True
except ImportError:
    _HAY_NOMBRES = False
# Subir este número hace que se vuelvan a revisar todas las webs (gratis, ~15 min).
# v3 (22/11/2026): el nombre del dueño tiene que ser un nombre de pila conocido. Sin gender-guesser
# instalado se queda en 2, para no volver a bajar todo y guardarlo sin nombres.
BUSQUEDA_VERSION = 3 if _HAY_NOMBRES else 2
PALABRAS_CONTACTO = ("contact", "about", "get-in-touch", "reach-us", "location", "team", "connect",
                     "find-us", "visit", "info", "staff", "our-story", "hours")
RUTAS_COMUNES = ("/contact", "/contact-us", "/about", "/about-us")   # si la portada no tiene links de contacto
EXT_FALSAS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js", ".ico")
DOMINIOS_BASURA = (
    "example.com", "sentry.io", "wixpress.com", "sentry-next.wixpress.com", "domain.com",
    "email.com", "yourdomain.com", "yoursite.com", "godaddy.com", "squarespace.com",
    "schema.org", "w3.org", "wix.com", "mysite.com", "company.com", "test.com",
)
LOCALES_BASURA = ("user", "name", "your", "youremail", "email", "info@example", "username",
                  "johndoe", "john.doe", "firstname", "noreply", "no-reply", "donotreply",
                  "me", "example", "test", "sample", "someone", "yourname", "you")
GRATUITOS = ("gmail.com", "googlemail.com", "yahoo.com", "ymail.com", "outlook.com", "hotmail.com", "aol.com",
             "icloud.com", "me.com", "mac.com", "live.com", "msn.com", "proton.me", "protonmail.com", "comcast.net",
             "att.net", "sbcglobal.net", "verizon.net", "cox.net", "bellsouth.net")


def es_basura(email):
    """Mails que no son de nadie: textos de relleno de las plantillas web (me@me.com, example@mail.com),
    direcciones internas de Wix o de herramientas de errores (hash@sentry.wixpress.com)."""
    e = str(email or "").strip().lower()
    local, arroba, dom = e.partition("@")
    if not arroba or not local or "." not in dom:
        return True
    return (local in LOCALES_BASURA or dom in DOMINIOS_BASURA
            or any(dom.endswith("." + d) for d in DOMINIOS_BASURA)
            or "sentry" in dom.split(".")
            or bool(re.fullmatch(r"[0-9a-f]{20,}", local)))


def _cf(hexa):
    try:
        b = bytes.fromhex(hexa)
        return "".join(chr(x ^ b[0]) for x in b[1:])
    except ValueError:
        return ""


def extraer(html):
    from urllib.parse import unquote
    crudo = html
    html = unescape(html)
    html = re.sub(r"\\u0040|\\x40|\\100", "@", html)                  # @ escrito como en JavaScript
    encontrados = set(m.group(0) for m in RE_MAIL.finditer(html))
    encontrados |= {_cf(a or b) for a, b in RE_CF.findall(crudo)}
    encontrados |= {unquote(m) for m in RE_MAILTO.findall(html)}        # mailto:info%40negocio.com
    for local, dom in RE_OCULTO.findall(html):
        dom = re.sub(r"\s*[\[\(\{]\s*(?:dot|punto|\.)\s*[\]\)\}]\s*|\s*\.\s*", ".", dom)
        encontrados.add(f"{local}@{dom}")
    limpios = set()
    for e in encontrados:
        e = e.strip(".-_").lower()
        if not e or "@" not in e:
            continue
        if e.endswith(EXT_FALSAS) or es_basura(e):
            continue
        local, _, dom = e.partition("@")
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
    local = re.sub(r"^(u00[0-9a-f]{2})+", "", local)             # \u003einfo (texto de JavaScript) -> info
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
    mails = [m for m in mails if local(m) not in ROLES_NO and not es_basura(m)]
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


RESERVAS = ("opentable.com", "resy.com", "exploretock.com", "sevenrooms.com", "yelp.com/reservations",
            "vagaro.com", "booksy.com", "styleseat.com", "fresha.com", "glossgenius.com", "squareup.com/appointments",
            "square.site/book", "setmore.com", "acuityscheduling.com", "calendly.com", "mindbodyonline.com",
            "schedulicity.com", "joinblvd.com", "zenoti.com", "gettimely.com", "booker.com", "schedulista.com")
PEDIDOS = ("toasttab.com", "chownow.com", "doordash.com", "ubereats.com", "grubhub.com", "order.online",
           "slicelife.com", "menufy.com", "beyondmenu.com", "clover.com/online-ordering", "squareup.com/store")
GENERADORES_VIEJOS = ("frontpage", "dreamweaver", "iweb", "joomla! 1.", "wordpress 3.", "wordpress 4.",
                      "homestead", "intuit", "web.com sitebuilder", "yahoo! sitebuilder", "netobjects")


def senales_web(html, url_final, ahora=None):
    """Señales para ofrecer otros servicios, sacadas gratis de la portada que ya se bajó."""
    from datetime import date
    anio = (ahora or date.today()).year
    h = (html or "").lower()
    anios = [int(a) for a in re.findall(r"(?:©|&copy;|copyright)\s*(?:\d{4}\s*[-–]\s*)?((?:19|20)\d{2})", h)]
    gen = re.search(r"""<meta[^>]+name=["']generator["'][^>]+content=["']([^"']+)""", h)
    generador = gen.group(1) if gen else ""
    return {
        "movil": bool(re.search(r"""<meta[^>]+name=["']viewport["']""", h)),
        "https": str(url_final or "").lower().startswith("https://"),
        "anio_copyright": max(anios) if anios else None,
        "vieja": (bool(anios) and max(anios) <= anio - 3) or any(g in generador for g in GENERADORES_VIEJOS)
                 or ".swf" in h,
        "reservas": any(x in h for x in RESERVAS),
        "pedidos": any(x in h for x in PEDIDOS),
        "instagram": "instagram.com/" in h,
        "facebook": "facebook.com/" in h,
    }


NO_SON_NOMBRES = {"The", "Our", "Your", "We", "She", "He", "They", "This", "That", "Meet", "About", "Owner",
                  "Founder", "Chef", "Manager", "Team", "Family", "Since", "With", "And", "For", "Contact", "Call",
                  "Restaurant", "Salon", "Nails", "Spa", "Moving", "Movers", "Property", "Management", "Group",
                  "Company", "Services", "Inc", "Llc", "Kitchen", "Bar", "Grill", "Cafe", "Studio", "Home", "Homes",
                  "Real", "Estate", "Realty", "Family", "Is", "Are", "Operated", "Owned", "Serving",
                  "Locally", "Independently", "Proudly", "Woman", "Veteran", "Minority", "Of", "Since", "Mr", "Mrs", "Ms", "Dr", "Hours", "Menu", "Welcome", "Hello", "Proud"}
RE_DUENO = [
    # Dentro de un lookahead para que "Meet the owner. Owner: Maria" no se coma el segundo "Owner".
    re.compile(r"(?=\b(?i:owner|founder|co-founder|proprietor|owned by|founded by)\s*(?:[:\-–,]|(?i:is)|&)?\s*"
               r"([A-Z][a-z]{2,14})\b)"),
    re.compile(r"\b([A-Z][a-z]{2,14})\s+[A-Z][a-z]{1,20}\s*,?\s*(?:\(|-|–|—)?\s*(?i:the\s+)?"
               r"(?i:owner|founder|co-founder|proprietor)\b"),
]


_DETECTOR = None


def es_nombre_de_pila(n):
    """¿Es un nombre de pila conocido? (diccionario de unos 40.000 nombres de gender-guesser).
    Descarta "Portal", "Login", "Midtown"... que salían de botones como "Owner Portal".
    Sin la librería instalada no arriesga: devuelve False."""
    global _DETECTOR
    if _DETECTOR is None:
        try:
            import gender_guesser.detector as g
            _DETECTOR = g.Detector(case_sensitive=False)
        except ImportError:
            _DETECTOR = False
    return bool(_DETECTOR) and _DETECTOR.get_gender(n) != "unknown"


def dueno_web(html):
    """Nombre de pila del dueño si la web lo dice ("Owner: Maria Lopez", "Founded by Mario"). Puede ser
    None. Todavía no se usa en los mails: primero hay que ver qué tan seguido acierta."""
    texto = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html or "", flags=re.S | re.I)
    texto = unescape(re.sub(r"<[^>]+>", " ", texto))
    texto = re.sub(r"\s+", " ", texto)
    nombres = collections.Counter()
    for rx in RE_DUENO:
        for n in rx.findall(texto):
            n = n.strip().capitalize()
            if n not in NO_SON_NOMBRES and es_nombre_de_pila(n):
                nombres[n] += 1
    return nombres.most_common(1)[0][0] if nombres else None


def buscar_en_web(url, dominio):
    s = requests.Session()
    s.headers.update(HEADERS)
    html, final = None, url
    for v in variantes(url):
        html, final = _bajar(s, v)
        if html is not None:
            break
    if html is None:
        return {"estado": "web caída o bloqueada", "email": None, "emails": [], "v": BUSQUEDA_VERSION}
    mails = extraer(html)
    senales = senales_web(html, final)
    textos = [html]
    host = (urlparse(final).hostname or "").lower()
    sin_www = host[4:] if host.startswith("www.") else host
    candidatos = []
    for href in RE_HREF.findall(html):
        if href.lower().startswith(("mailto:", "tel:", "javascript:")):
            continue
        absoluta = urljoin(final, href).split("#")[0]
        h = (urlparse(absoluta).hostname or "").lower()
        h = h[4:] if h.startswith("www.") else h
        ruta = urlparse(absoluta).path.lower()
        if h == sin_www and any(p in ruta for p in PALABRAS_CONTACTO) and absoluta not in candidatos:
            candidatos.append(absoluta)
    # Las de contacto primero: ahí suele estar el mail.
    candidatos.sort(key=lambda u: 0 if "contact" in u.lower() else 1)
    if not elegir(mails, dominio) and not candidatos:
        candidatos = [urljoin(final, r) for r in RUTAS_COMUNES]
    for extra in candidatos[:4]:
        if elegir(mails, dominio) and dominio and any(m.endswith("@" + dominio) for m in mails):
            break                                     # ya hay uno del dominio propio: no hace falta seguir
        h2, _ = _bajar(s, extra)
        if h2:
            mails |= extraer(h2)
            textos.append(h2)
            senales["reservas"] = senales["reservas"] or any(x in h2.lower() for x in RESERVAS)
    return {"estado": "ok", "email": elegir(mails, dominio), "emails": sorted(mails)[:10],
            "senales": senales, "dueno": dueno_web(" ".join(textos)), "v": BUSQUEDA_VERSION}


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
            mx = [str(a.get("data", "")).split() for a in d.get("Answer", []) if a.get("type") == 15]
            # "0 ." es un MX nulo: el dominio declara que no recibe mails.
            return any(len(x) >= 2 and x[1].rstrip(".") for x in mx) or any(len(x) == 1 for x in mx)
    return None


def chequear_mx(dominios, previos=None, hilos=12):
    resultados = dict(previos or {})
    pendientes = [d for d in dominios if d not in resultados]
    with ThreadPoolExecutor(max_workers=hilos) as ex:
        for d, ok in zip(pendientes, ex.map(tiene_mx, pendientes)):
            if ok is not None:
                resultados[d] = ok
    return resultados


def necesita_revision(r):
    """¿Hay que (volver a) mirar esta web? Nueva, caída sin reintentar, o revisada con una búsqueda
    más vieja sin haber encontrado mail (o sin las señales)."""
    if r is None:
        return True
    if r.get("estado") != "ok":
        return not r.get("reintento")                 # una web caída se reintenta una sola vez
    return r.get("v", 1) < BUSQUEDA_VERSION


def buscar_todos(webs, previos=None, al_avanzar=None, hilos=12):
    """webs: {dominio: url}. Devuelve {dominio: resultado}. Saltea los ya revisados, salvo
    las webs que no cargaron: a esas les da un segundo intento."""
    resultados = dict(previos or {})
    pendientes = {d: u for d, u in webs.items() if necesita_revision(resultados.get(d))}
    reintentos = {d for d in pendientes if d in resultados}
    with ThreadPoolExecutor(max_workers=hilos) as ex:
        futuros = {ex.submit(buscar_en_web, u, d): d for d, u in pendientes.items()}
        for i, f in enumerate(as_completed(futuros), 1):
            d = futuros[f]
            previo = resultados.get(d)
            try:
                nuevo = f.result()
            except Exception as e:  # una web rara no frena al resto
                nuevo = {"estado": f"error: {type(e).__name__}", "email": None, "emails": []}
            if previo and previo.get("estado") == "ok":
                # Se volvía a mirar con la búsqueda nueva: nunca se pierde lo que ya se había encontrado.
                if nuevo.get("estado") != "ok":
                    nuevo = {**previo, "v": BUSQUEDA_VERSION}
                elif not nuevo.get("email") and previo.get("email"):
                    nuevo = {**nuevo, "email": previo["email"],
                             "emails": sorted(set(nuevo.get("emails") or []) | set(previo.get("emails") or []))[:10]}
            elif d in reintentos:
                nuevo["reintento"] = True
            resultados[d] = nuevo
            if al_avanzar:
                al_avanzar(i, len(pendientes))
    return resultados
