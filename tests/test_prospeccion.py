"""Tests de la prospección: emails.py, analisis.py y prospectar.py (datos inventados, sin red)."""
import csv
import json
from datetime import datetime, timedelta, timezone

import pytest

import analisis as A
import config as C
import emails as E
import prospectar as P

AHORA = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


def hace(dias):
    return (AHORA - timedelta(days=dias)).isoformat()


def resena(dias, estrellas=5, texto="Great service, very friendly staff", nombre="Ann Smith",
           respuesta="", origen="Google", url=""):
    return {"publishedAtDate": hace(dias), "stars": estrellas, "text": texto, "name": nombre,
            "responseFromOwnerText": respuesta, "responseFromOwnerDate": hace(dias - 1) if respuesta else None,
            "reviewOrigin": origen, "reviewUrl": url}


# =============================================================================
# emails.py
# =============================================================================
class TestExtraer:
    def test_mails_normales_y_entidades(self):
        html = '<a href="mailto:Info@PizzaMario-X.com">x</a> o escribí a hola&#64;pizzamario-x.com.'
        assert E.extraer(html) == {"info@pizzamario-x.com", "hola@pizzamario-x.com"}

    def test_cloudflare_protegido(self):
        clave = 0x42
        texto = "info@neg-x.com"
        hexa = f"{clave:02x}" + "".join(f"{ord(c) ^ clave:02x}" for c in texto)
        assert E.extraer(f'<a data-cfemail="{hexa}">[email protected]</a>') == {texto}

    @pytest.mark.parametrize("basura", ["logo@2x.png", "user@example.com", "x@sentry.io",
                                        "noreply@neg-x.com", "yourname@neg-x.com".replace("yourname", "your")])
    def test_descarta_basura(self, basura):
        assert E.extraer(basura) == set()


class TestBasura:
    @pytest.mark.parametrize("mail", ["me@me.com", "example@mail.com", "test@neg-x.com", "your@neg-x.com",
                                      "0c52cb89aa4d4154857a1584b6701db6@sentry.wixpress.com",
                                      "abc@sentry-next.wixpress.com", "x@sentry.io", "info@example.com",
                                      "sin-arroba", "a@sindominio", ""])
    def test_es_basura(self, mail):
        assert E.es_basura(mail)

    @pytest.mark.parametrize("mail", ["brasserie19@brasserie19.com", "info@neg-x.com", "dueno@gmail.com",
                                      "mail@neg-x.com",
                                      "cafe2024@neg-x.com", "deadbeef@neg-x.com"])
    def test_no_es_basura(self, mail):
        assert not E.es_basura(mail)

    def test_elegir_no_cae_en_relleno(self):
        guardados = ["0c52cb89aa4d4154857a1584b6701db6@sentry.wixpress.com", "me@me.com", "zz-dueno@gmail.com"]
        assert E.elegir(guardados, "agave-x.com") == "zz-dueno@gmail.com"
        assert E.elegir(["me@me.com", "example@mail.com"], "agave-x.com") is None


class TestNormalizar:
    @pytest.mark.parametrize("crudo,limpio", [
        ("%20info@neg-x.com", "info@neg-x.com"),
        ("499-9324relocation@movers-x.com", "relocation@movers-x.com"),
        ("u003einfo@neg-x.com", "info@neg-x.com"),
        ("u003eu0022sales@neg-x.com", "sales@neg-x.com"),
        ("<Info@Neg-X.com>", "info@neg-x.com"),
        ("sin-arroba", ""),
        ("mal formado@neg-x.com", "formado@neg-x.com"),
    ])
    def test_casos(self, crudo, limpio):
        assert E.normalizar(crudo) == limpio


class TestElegir:
    def test_prefiere_el_del_dominio_propio(self):
        assert E.elegir(["owner@gmail.com", "info@neg-x.com", "x@disenador-x.com"], "neg-x.com") == "info@neg-x.com"

    def test_subdominio_cuenta_como_propio(self):
        assert E.elegir(["a@mail.neg-x.com", "b@gmail.com"], "neg-x.com") == "a@mail.neg-x.com"

    def test_despues_gratuito(self):
        assert E.elegir(["x@otro-x.com", "dueno@yahoo.com"], "neg-x.com") == "dueno@yahoo.com"

    def test_descarta_areas_que_no_compran(self):
        assert E.elegir(["privacy@neg-x.com", "careers@neg-x.com"], "neg-x.com") is None

    def test_administracion_solo_si_no_hay_otro(self):
        assert E.elegir(["billing@neg-x.com", "hola@neg-x.com"], "neg-x.com") == "hola@neg-x.com"
        assert E.elegir(["billing@neg-x.com"], "neg-x.com") == "billing@neg-x.com"

    def test_vacio(self):
        assert E.elegir([], "neg-x.com") is None and E.elegir(None, None) is None


def test_gratuitos_coinciden_con_la_campana():
    """Los dominios gratuitos de la búsqueda y los de la campaña tienen que ser los mismos."""
    import campana
    assert campana.DOMINIOS_LIBRES <= set(E.GRATUITOS)


def test_variantes_de_la_web():
    v = E.variantes("www.neg-x.com/home?utm=1")
    assert v[0] == "http://www.neg-x.com/home?utm=1"
    assert "https://neg-x.com/" in v and "https://www.neg-x.com/" in v and len(v) == len(set(v))


class SesionDNS:
    def __init__(self, respuestas):
        self.respuestas = list(respuestas)

    def get(self, url, **kw):
        r = self.respuestas.pop(0)
        if isinstance(r, Exception):
            raise r

        class Resp:
            def json(self_inner):
                return r
        return Resp()


class TestMX:
    def test_tiene_mx(self):
        assert E.tiene_mx("neg-x.com", SesionDNS([{"Status": 0, "Answer": [
            {"type": 15, "data": "10 mx.proveedor-x.com."}]}])) is True

    def test_dominio_inexistente(self):
        assert E.tiene_mx("neg-x.com", SesionDNS([{"Status": 3}])) is False

    def test_sin_registros_mx(self):
        assert E.tiene_mx("neg-x.com", SesionDNS([{"Status": 0, "Answer": [{"type": 1, "data": "1.2.3.4"}]}])) is False

    def test_mx_nulo_no_recibe(self):
        assert E.tiene_mx("neg-x.com", SesionDNS([{"Status": 0, "Answer": [{"type": 15, "data": "0 ."}]}])) is False

    def test_si_falla_el_primero_prueba_el_segundo(self):
        import requests
        assert E.tiene_mx("neg-x.com", SesionDNS([requests.ConnectionError(), {"Status": 3}])) is False

    def test_no_se_pudo_saber(self):
        import requests
        assert E.tiene_mx("neg-x.com", SesionDNS([requests.Timeout(), ValueError()])) is None

    def test_chequear_mx_reusa_lo_anterior(self, monkeypatch):
        llamados = []
        monkeypatch.setattr(E, "tiene_mx", lambda d: llamados.append(d) or (d != "malo-x.com" and None))
        r = E.chequear_mx(["viejo-x.com", "malo-x.com", "duda-x.com"], {"viejo-x.com": True})
        assert r == {"viejo-x.com": True, "malo-x.com": False} and "viejo-x.com" not in llamados


class SesionWeb:
    """Webs inventadas: {url: (status, html)}."""
    PAGINAS = {}

    def __init__(self):
        self.headers = {}

    def get(self, url, **kw):
        status, html = self.PAGINAS.get(url, (404, ""))

        class Crudo:
            def read(self_inner, n, decode_content=True):
                return html.encode()

        class Resp:
            status_code = status
            headers = {"Content-Type": "text/html; charset=utf-8"}
            encoding = "utf-8"
            raw = Crudo()
        Resp.url = url
        return Resp()


class TestBuscarEnWeb:
    def test_sigue_paginas_de_contacto(self, monkeypatch):
        SesionWeb.PAGINAS = {
            "http://neg-x.com": (200, '<a href="/contact-us">Contacto</a> <a href="https://otro-x.com/contact">x</a>'),
            "http://neg-x.com/contact-us": (200, "Escribinos: hola@neg-x.com"),
        }
        monkeypatch.setattr(E.requests, "Session", SesionWeb)
        r = E.buscar_en_web("neg-x.com", "neg-x.com")
        assert r == {"estado": "ok", "email": "hola@neg-x.com", "emails": ["hola@neg-x.com"]}

    def test_prueba_variantes_si_no_carga(self, monkeypatch):
        SesionWeb.PAGINAS = {"https://neg-x.com/": (200, "info@neg-x.com")}
        monkeypatch.setattr(E.requests, "Session", SesionWeb)
        assert E.buscar_en_web("http://www.neg-x.com", "neg-x.com")["email"] == "info@neg-x.com"

    def test_web_caida(self, monkeypatch):
        SesionWeb.PAGINAS = {}
        monkeypatch.setattr(E.requests, "Session", SesionWeb)
        assert E.buscar_en_web("neg-x.com", "neg-x.com")["estado"] == "web caída o bloqueada"


def test_buscar_todos_reintenta_una_vez_las_caidas(monkeypatch):
    llamados = []

    def falso(url, dominio):
        llamados.append(dominio)
        if dominio == "explota-x.com":
            raise RuntimeError("web rara")
        return {"estado": "web caída o bloqueada", "email": None, "emails": []}
    monkeypatch.setattr(E, "buscar_en_web", falso)
    previos = {"ok-x.com": {"estado": "ok", "email": "a@ok-x.com", "emails": []},
               "caida-x.com": {"estado": "web caída o bloqueada"},
               "ya-reintentada-x.com": {"estado": "web caída o bloqueada", "reintento": True}}
    webs = {d: d for d in ["ok-x.com", "caida-x.com", "ya-reintentada-x.com", "nueva-x.com", "explota-x.com"]}
    r = E.buscar_todos(webs, previos, hilos=2)
    assert sorted(llamados) == ["caida-x.com", "explota-x.com", "nueva-x.com"]
    assert r["caida-x.com"]["reintento"] is True and "reintento" not in r["nueva-x.com"]
    assert r["explota-x.com"]["estado"] == "error: RuntimeError"


# =============================================================================
# analisis.py
# =============================================================================
class TestAnalizarWeb:
    @pytest.mark.parametrize("url,esperado", [
        (None, ("sin_web", None)),
        ("  ", ("sin_web", None)),
        ("https://www.facebook.com/pizzamario", ("red_social", None)),
        ("https://order.toasttab.com/x", ("red_social", None)),
        ("https://pizzamario.wixsite.com/menu", ("propia", "pizzamario.wixsite.com")),
        ("https://sites.google.com/view/pizzamario/home", ("propia", "sites.google.com/view/pizzamario")),
        ("https://www.pizzamario-x.com/menu", ("propia", "pizzamario-x.com")),
        ("pizzamario-x.com", ("propia", "pizzamario-x.com")),
        ("https://order.pizzamario-x.com", ("propia", "pizzamario-x.com")),
        ("https://www.pizzeria-x.com.mx", ("propia", "pizzeria-x.com.mx")),
        ("https://shop.tienda-x.co.uk/a", ("propia", "tienda-x.co.uk")),
    ])
    def test_casos(self, url, esperado):
        assert A.analizar_web(url) == esperado

    def test_dos_negocios_distintos_con_sufijo_doble_no_se_juntan(self):
        assert A.analizar_web("https://uno-x.com.mx")[1] != A.analizar_web("https://dos-x.com.mx")[1]


class TestCadenas:
    def test_marca_en_el_nombre(self):
        assert A.es_marca_cadena("Two Men and a Truck Atlanta", rubro="mudanzas") == "two men and a truck"

    def test_marca_en_la_web(self):
        assert A.es_marca_cadena("Atlanta Movers", "bekinsmoving.com", "mudanzas") == "bekins"

    def test_no_confunde_palabras_sueltas(self):
        assert A.es_marca_cadena("Midasco Pizza", rubro="restaurantes") is None
        assert A.es_marca_cadena("Subwaystation Cafe", rubro="restaurantes") is None

    def test_marca_de_otro_rubro_no_cuenta(self):
        assert A.es_marca_cadena("Mayflower Seafood", rubro="restaurantes") is None
        assert A.es_marca_cadena("Rollins Property Management", rubro="administradoras") is None
        assert A.es_marca_cadena("Mayflower Movers", rubro="mudanzas") == "mayflower"

    def test_marcas_generales_en_cualquier_rubro(self):
        assert A.es_marca_cadena("The Home Depot Moving Help", rubro="mudanzas") == "home depot"

    def test_sin_rubro_usa_todas(self):
        assert A.es_marca_cadena("Mayflower Seafood") == "mayflower"

    @pytest.mark.parametrize("url,esperado", [
        ("https://chain-x.com/locations/atlanta-midtown", True),
        ("https://chain-x.com/our-locations/houston", True),
        ("https://chain-x.com/branches/la", True),
        ("https://chain-x.com/ga/atlanta", True),
        ("https://chain-x.com/tx/houston-heights", True),
        ("https://pizza-x.com/location", False),
        ("https://pizza-x.com/locations", False),
        ("https://pizza-x.com/locations/", False),
        ("https://pizza-x.com/la/menu", False),
        ("https://pizza-x.com/ga/about", False),
        ("https://pizza-x.com/menu/specials", False),
        ("https://pizza-x.com/", False),
    ])
    def test_web_de_sucursales(self, url, esperado):
        assert A.web_de_sucursales(url) is esperado


class TestMetricas:
    def test_sin_resenas(self):
        m = A.metricas_resenas([], AHORA)
        assert m["n_muestra"] == 0 and m["tasa_respuesta"] is None and m["sin_resp_reciente"] == 0

    def test_cuenta_bien(self):
        rs = [resena(5, 1, "Terrible"), resena(20), resena(40, respuesta="Thanks!"),
              resena(200, 2, "Bad"), resena(10, origen="Tripadvisor")]
        m = A.metricas_resenas(rs, AHORA)
        assert m["n_muestra"] == 4                      # la de Tripadvisor no cuenta
        assert m["respondidas"] == 1 and m["tasa_respuesta"] == 0.25
        assert m["sin_resp_total"] == 3 and m["sin_resp_reciente"] == 2
        assert m["negativa_sin_resp"] and m["negativa_estrellas"] == 1  # la de 200 días es vieja
        assert m["dejo_de_responder"] is True
        assert m["resenas_por_mes"] == round(4 / 200 * 30, 2)

    def test_pocas_resenas_no_miden_tasa(self):
        m = A.metricas_resenas([resena(5), resena(6)], AHORA)
        assert m["tasa_respuesta"] is None

    def test_fechas_raras_se_ignoran(self):
        rs = [{"publishedAtDate": "ayer", "stars": 5}, {"stars": 4}, resena(3)]
        assert A.metricas_resenas(rs, AHORA)["n_muestra"] == 1

    def test_puntaje(self):
        m = {"sin_resp_reciente": 4, "negativa_sin_resp": True, "negativa_estrellas": 1, "resenas_por_mes": 3}
        p, porque = A.puntaje(m, {"totalScore": 4.2, "isAdvertisement": True})
        assert p == 10 and "rating 4.2" in porque and "anuncios" in porque
        p, _ = A.puntaje({"sin_resp_reciente": 0, "negativa_sin_resp": False, "resenas_por_mes": 0.2},
                         {"totalScore": 4.9})
        assert p == 0


def lugar(titulo, web, rubro_busqueda="restaurant", reviews=None, **extra):
    base = {"title": titulo, "website": web, "searchString": rubro_busqueda, "categoryName": "Restaurant",
            "categories": ["Restaurant"], "placeId": "ChIJ" + titulo.replace(" ", ""), "reviewsCount": 120,
            "totalScore": 4.3, "reviews": reviews if reviews is not None else
            [resena(3, 1, "Cold food, rude"), resena(8), resena(15), resena(30)]}
    base.update(extra)
    return base


class TestConstruirNegocios:
    def armar(self, bloques):
        return {n["nombre"]: n for n in A.construir_negocios(bloques)}

    def test_independiente_calificado(self):
        n = self.armar([("atlanta", {"fecha": AHORA.isoformat(), "items": [lugar("Pizza Mario", "pizzamario-x.com")]})])
        f = n["Pizza Mario"]
        assert f["independiente"] and f["reclamado"] and f["prospecto_calificado"] and f["puntaje"] > 0

    def test_web_compartida_en_dos_ciudades(self):
        n = self.armar([("atlanta", {"fecha": AHORA.isoformat(), "items": [lugar("Taqueria A", "taco-x.com")]}),
                        ("houston", {"fecha": AHORA.isoformat(), "items": [lugar("Taqueria B", "taco-x.com")]})])
        assert all(f["cadena"] and "web compartida" in f["motivo_cadena"] for f in n.values())

    def test_mismo_nombre_en_dos_ciudades(self):
        n = A.construir_negocios([
            ("atlanta", {"fecha": AHORA.isoformat(), "items": [lugar("Burger Joint", "bj1-x.com", placeId="ChIJ1")]}),
            ("houston", {"fecha": AHORA.isoformat(), "items": [lugar("Burger Joint", "bj2-x.com", placeId="ChIJ2")]})])
        assert all(f["motivo_cadena"] == "mismo nombre en varias ciudades" for f in n)

    def test_un_solo_local_con_pagina_location_no_es_cadena(self):
        n = self.armar([("atlanta", {"fecha": AHORA.isoformat(),
                                     "items": [lugar("Pizza Mario", "https://pizzamario-x.com/location")]})])
        assert not n["Pizza Mario"]["cadena"]

    def test_cerrado_sin_reclamar_y_otra_categoria(self):
        items = [lugar("Cerrado", "c-x.com", permanentlyClosed=True),
                 lugar("Sin Reclamar", "s-x.com", claimThisBusiness=True),
                 lugar("Tienda", "t-x.com", categoryName="Grocery store", categories=["Grocery store"])]
        n = self.armar([("atlanta", {"fecha": AHORA.isoformat(), "items": items})])
        assert not n["Cerrado"]["valido"] and "cerrado" in n["Cerrado"]["descarte"]
        assert n["Sin Reclamar"]["independiente"] and not n["Sin Reclamar"]["reclamado"]
        assert n["Sin Reclamar"]["puntaje"] == 0 and not n["Sin Reclamar"]["prospecto_calificado"]
        assert not n["Tienda"]["categoria_ok"]

    def test_busqueda_de_otro_rubro_se_ignora(self):
        assert A.construir_negocios([("atlanta", {"items": [lugar("X", "x-x.com", "dentist")]})]) == []

    def test_no_repite_el_mismo_negocio(self):
        it = lugar("Pizza Mario", "pizzamario-x.com")
        assert len(A.construir_negocios([("atlanta", {"items": [it, dict(it)]})])) == 1


# =============================================================================
# prospectar.py
# =============================================================================
def test_slug_y_zonas():
    assert P.slug("Downtown, Atlanta (GA) — Ñandú") == "downtown-atlanta-ga-nandu"
    assert P.ubicacion_alternativa("Downtown, Atlanta, Georgia, USA") == "Downtown Atlanta, Georgia, USA"
    assert P.ubicacion_alternativa("Atlanta") == "Atlanta"


def test_zonas_alternan_ciudades(monkeypatch):
    monkeypatch.setattr(P.C, "PROSP_ZONAS", {"a": ["a1", "a2", "a3"], "b": ["b1"]})
    assert P.zonas_en_orden() == [("a", "a1"), ("b", "b1"), ("a", "a2"), ("a", "a3")]


class TestGancho:
    def test_elige_la_negativa_mas_nueva(self):
        g = P.gancho({"reviews": [resena(10, 1, "Rude staff, cold food", "Bob Lee"), resena(2, 2, "Bad, slow", "Ana Paz"),
                                  resena(4, 5, "Loved it!", "Cami Ruiz")]}, AHORA)
        assert g["gancho_tipo"] == "negativa" and g["gancho_autor"] == "Ana"
        assert g["gancho2_estrellas"] == 5 and g["gancho2_autor"] == "Cami"
        assert g["sin_responder_muestra"] == 3

    def test_negativa_con_texto_positivo_es_un_error_de_puntaje(self):
        g = P.gancho({"reviews": [resena(2, 1, "Amazing food, great service, love it"), resena(5, 4, "Nice place")]},
                     AHORA)
        assert g["gancho_tipo"] == "sin responder" and g["gancho_estrellas"] == 4

    def test_ignora_respondidas_y_otras_plataformas(self):
        g = P.gancho({"reviews": [resena(1, 1, "Bad", respuesta="Sorry!"), resena(2, 1, "Bad", origen="Yelp"),
                                  resena(3, 5, "Good")]}, AHORA)
        assert g["gancho_estrellas"] == 5 and g["gancho2_estrellas"] == ""

    def test_sin_nada_para_responder(self):
        assert P.gancho({"reviews": [resena(1, respuesta="Thanks")]}, AHORA) == {}
        assert P.gancho({}, AHORA) == {}

    def test_limpia_html(self):
        g = P.gancho({"reviews": [resena(1, 5, "Great<br>food <b>here</b>")]}, AHORA)
        assert g["gancho_texto"] == "Great\nfood here"


class TestRelacionado:
    def test_comparte_nombre(self):
        assert P.relacionado("info@mariospizzeria.com", "Mario's Pizzeria", "https://mariospizza-x.com")

    def test_disenador_web_no(self):
        assert not P.relacionado("hello@webdesigns-x.com", "Pizza Mario", "https://pizzamario-x.com")

    def test_la_ciudad_sola_no_alcanza(self):
        assert not P.relacionado("info@atlantawebstudio.com", "Atlanta Nail Spa", "https://atlnails-x.com")


def test_tipo_de_email():
    assert P.tipo_email("a@neg-x.com", "neg-x.com") == "propio"
    assert P.tipo_email("a@ymail.com", "neg-x.com") == "gratuito"
    assert P.tipo_email("a@otro-x.com", "neg-x.com") == "otro dominio"
    assert P.tipo_email("", "neg-x.com") == ""


def test_espanol():
    assert P.es_espanol("La comida muy rica y el servicio excelente")
    assert not P.es_espanol("Great food and service, will come back")


# --- cmd_lista de punta a punta ------------------------------------------------
def usar_carpeta(monkeypatch, tmp_path):
    """Toda la prospección en una carpeta temporal (sin git: no se sube nada)."""
    salida = tmp_path / "salida"
    d = salida / "prospeccion"
    for nombre, valor in [("SALIDA", salida), ("DIR", d), ("CRUDO_P", d / "crudo"), ("CRUDO", d / "estudio"),
                          ("ZONAS", d / "zonas.json"), ("EMAILS", d / "emails.json"), ("MX", d / "mx.json"),
                          ("EXPORTADOS", d / "exportados.json"), ("VIEJO", tmp_path / "datos")]:
        monkeypatch.setattr(P, nombre, valor)
    (d / "crudo").mkdir(parents=True)


@pytest.fixture
def lista(tmp_path, monkeypatch):
    usar_carpeta(monkeypatch, tmp_path)
    monkeypatch.setattr(P.C, "PROSP_ZONAS", {"atlanta": ["Midtown, Atlanta, Georgia, USA"]})
    monkeypatch.setattr(P.C, "PROSP_PRIORIDADES", ["A", "B", "C"])
    return tmp_path


def correr_lista(tmp, items, mails, mx=None, monkeypatch=None):
    P.guardar_json(P.CRUDO_P / "atlanta__midtown.json.gz",
                   {"ciudad": "atlanta", "zona": "Midtown, Atlanta, Georgia, USA", "fecha": AHORA.isoformat(),
                    "items": items})
    import emails as EM
    monkeypatch.setattr(EM, "buscar_todos", lambda webs, previos, avanzar=None: {**previos, **mails})
    monkeypatch.setattr(EM, "chequear_mx", lambda doms, previos: {**{d: True for d in doms}, **(mx or {})})
    filas, nuevos = P.cmd_lista()
    with open(P.SALIDA / "prospectos_todos.csv", encoding="utf-8-sig") as f:
        return filas, nuevos, list(csv.DictReader(f))


def test_lista_completa(lista, monkeypatch):
    items = [
        lugar("Pizza Mario", "pizzamario-x.com"),                                    # A
        lugar("Taco Loco", "tacoloco-x.com", reviews=[resena(400, 4, "ok"), resena(500)]),   # C: señal vieja
        lugar("Sin Mail", "sinmail-x.com"),                                          # sin mail
        lugar("Rebota", "rebota-x.com"),                                             # MX malo
        lugar("Disenador", "disenador-x.com"),                                       # mail de otro dominio -> C
        lugar("Ya Responde", "responde-x.com", reviews=[resena(d, respuesta="Thanks!") for d in (2, 4, 6, 8)]),
    ]
    mails = {
        "pizzamario-x.com": {"estado": "ok", "email": "info@pizzamario-x.com", "emails": ["info@pizzamario-x.com"]},
        "tacoloco-x.com": {"estado": "ok", "email": "hola@tacoloco-x.com", "emails": ["hola@tacoloco-x.com"]},
        "sinmail-x.com": {"estado": "ok", "email": None, "emails": []},
        "rebota-x.com": {"estado": "ok", "email": "info@rebota-x.com", "emails": ["info@rebota-x.com"]},
        "disenador-x.com": {"estado": "ok", "email": "hi@webstudio-x.com", "emails": ["hi@webstudio-x.com"]},
    }
    filas, nuevos, csv_filas = correr_lista(lista, items, mails, {"rebota-x.com": False}, monkeypatch)
    por = {f["nombre"]: f for f in csv_filas}
    assert set(por) == {"Pizza Mario", "Taco Loco", "Disenador"}
    assert por["Pizza Mario"]["prioridad"] == "A" and por["Pizza Mario"]["email_tipo"] == "propio"
    assert por["Pizza Mario"]["gancho_tipo"] == "negativa" and por["Pizza Mario"]["zona"] == "Midtown"
    assert por["Taco Loco"]["prioridad"] == "C"
    assert por["Disenador"]["prioridad"] == "C" and por["Disenador"]["email_tipo"] == "otro dominio"
    assert [f["nombre"] for f in csv_filas][0] == "Pizza Mario"            # ordenado por prioridad
    assert len(nuevos) == 3
    # Segunda corrida: los mismos no son nuevos y conservan la fecha de detección.
    filas2, nuevos2, _ = correr_lista(lista, items, mails, {"rebota-x.com": False}, monkeypatch)
    assert nuevos2 == [] and {f["detectado"] for f in filas2} == {f["detectado"] for f in filas}


def test_lista_no_pierde_el_mejor_mail_si_la_web_tiene_muchos(lista, monkeypatch):
    """La búsqueda guarda solo 10 mails (en orden alfabético): el elegido tiene que seguir contando."""
    mails = {"pizzamario-x.com": {"estado": "ok", "email": "info@pizzamario-x.com",
                                  "emails": [f"privacy{i}@x-x.com" for i in range(10)]}}
    _, _, csv_filas = correr_lista(lista, [lugar("Pizza Mario", "pizzamario-x.com")], mails, None, monkeypatch)
    assert csv_filas[0]["email"] == "info@pizzamario-x.com"


def test_lista_un_mail_por_negocio(lista, monkeypatch):
    items = [lugar("Pizza Mario", "pizzamario-x.com"),
             lugar("Pizza Mario Bar", "pizzamario-x.com", rubro_busqueda="restaurant", placeId="ChIJotro")]
    mails = {"pizzamario-x.com": {"estado": "ok", "email": "info@pizzamario-x.com", "emails": ["info@pizzamario-x.com"]}}
    _, _, csv_filas = correr_lista(lista, items, mails, None, monkeypatch)
    assert [f["email"] for f in csv_filas] == ["info@pizzamario-x.com"]


def test_lista_sin_datos(lista):
    with pytest.raises(SystemExit):
        P.cmd_lista()


def test_lista_exigente_solo_a(lista, monkeypatch):
    """Con PROSP_PRIORIDADES = ["A"] (lo de hoy) quedan solo los A; los B, solo con negativa si se suman."""
    items = [lugar("Pizza Mario", "pizzamario-x.com"),                                       # A
             lugar("Taco Loco", "tacoloco-x.com", reviews=[resena(400, 4, "ok"), resena(500)]),  # C
             lugar("Ya Responde", "responde-x.com", reviews=[resena(3, 1, "Rude, cold food"), resena(5),
                   resena(9, respuesta="Thanks"), resena(12, respuesta="Thanks"), resena(14, respuesta="Thanks"),
                   resena(16, respuesta="Thanks"), resena(18, respuesta="Thanks"), resena(19, respuesta="Thanks")]),
             lugar("Responde Sin Negativa", "rsn-x.com", reviews=[resena(5), resena(8, respuesta="Thanks"),
                   resena(9, respuesta="Thanks"), resena(12, respuesta="Thanks"), resena(14, respuesta="Thanks"),
                   resena(16, respuesta="Thanks"), resena(18, respuesta="Thanks"), resena(19, respuesta="Thanks")])]
    mails = {d: {"estado": "ok", "email": f"info@{d}", "emails": [f"info@{d}"]}
             for d in ("pizzamario-x.com", "tacoloco-x.com", "responde-x.com", "rsn-x.com")}
    monkeypatch.setattr(P.C, "PROSP_PRIORIDADES", ["A"])
    _, _, filas = correr_lista(lista, items, mails, None, monkeypatch)
    assert [f["nombre"] for f in filas] == ["Pizza Mario"]
    monkeypatch.setattr(P.C, "PROSP_PRIORIDADES", ["A", "B"])
    _, _, filas = correr_lista(lista, items, mails, None, monkeypatch)
    assert {f["nombre"]: f["prioridad"] for f in filas} == {"Pizza Mario": "A", "Ya Responde": "B"}


# --- cmd_buscar con un Apify inventado --------------------------------------------
class ApifyFalso:
    def __init__(self, libre=5.0, items_por_zona=None):
        self.usado, self.maximo = 5.0 - libre, 5.0
        self.items_por_zona = items_por_zona or {}
        self.arrancadas = []

    def credito(self):
        return self.usado, self.maximo

    def arrancar(self, actor, entrada, tope):
        self.arrancadas.append(entrada["locationQuery"])
        self.usado += 0.6
        return {"id": f"run{len(self.arrancadas)}"}

    def esperar(self, run_id, avanzar=None):
        return {"status": "SUCCEEDED", "defaultDatasetId": run_id, "usageTotalUsd": 0.6}

    def items(self, ds):
        zona = self.arrancadas[int(ds[3:]) - 1]
        return self.items_por_zona.get(zona, [{"title": "X"}])


@pytest.fixture
def buscar(tmp_path, monkeypatch):
    usar_carpeta(monkeypatch, tmp_path)
    monkeypatch.setattr(P.C, "PROSP_ZONAS", {"atlanta": ["Midtown, Atlanta, Georgia, USA", "Buckhead, Atlanta, Georgia, USA"],
                                             "houston": ["Heights, Houston, Texas, USA"]})
    monkeypatch.setattr(P, "costo_zona", lambda: 0.6)               # tope por zona: 0,66 + 0,10 de margen
    monkeypatch.setattr(P.C, "PROSP_RESERVA_USD", 0.0)
    monkeypatch.setattr(P, "tokens", lambda: ["t1"])
    return tmp_path


def con_cuentas(monkeypatch, **apis):
    monkeypatch.setattr(P, "tokens", lambda: list(apis))
    monkeypatch.setattr(P, "Apify", lambda t: apis[t])


def test_buscar_hasta_que_alcanza_el_credito(buscar, monkeypatch):
    api = ApifyFalso(libre=1.6)
    con_cuentas(monkeypatch, t1=api)
    assert P.cmd_buscar(confirmar=False) == 2
    assert api.arrancadas == ["Midtown, Atlanta, Georgia, USA", "Heights, Houston, Texas, USA"]
    assert P.zona_hecha("atlanta", "Midtown, Atlanta, Georgia, USA")
    assert P.archivo_zona("atlanta", "Midtown, Atlanta, Georgia, USA").name.endswith(".json.gz")


def test_buscar_pasa_a_la_siguiente_cuenta(buscar, monkeypatch):
    a, b, c = ApifyFalso(libre=0.5), ApifyFalso(libre=0.9), ApifyFalso(libre=5)
    con_cuentas(monkeypatch, t1=a, t2=b, t3=c)
    assert P.cmd_buscar(confirmar=False) == 3
    assert a.arrancadas == [] and len(b.arrancadas) == 1 and len(c.arrancadas) == 2


def test_buscar_respeta_la_reserva_para_las_tandas(buscar, monkeypatch):
    api = ApifyFalso(libre=3.0)
    con_cuentas(monkeypatch, t1=api)
    monkeypatch.setattr(P.C, "PROSP_RESERVA_USD", 2.0)
    assert P.cmd_buscar(confirmar=False) == 1                       # 3,00 - 0,76 = 2,24; otra la dejaría en 1,48


def test_buscar_con_maximo_de_zonas(buscar, monkeypatch):
    api = ApifyFalso(libre=5)
    con_cuentas(monkeypatch, t1=api)
    assert P.cmd_buscar(confirmar=False, max_zonas=1) == 1 and len(api.arrancadas) == 1


def test_retoma_con_la_misma_cuenta(buscar, monkeypatch):
    a, b = ApifyFalso(libre=5), ApifyFalso(libre=5)
    con_cuentas(monkeypatch, t1=a, t2=b)
    zona = "Midtown, Atlanta, Georgia, USA"
    import hashlib
    b.arrancadas.append(zona)                                       # la corrida run1 es de la cuenta 2
    P.guardar_json(P.ZONAS, {f"atlanta|{zona}": {"run_id": "run1", "cuenta": hashlib.sha256(b"t2").hexdigest()[:10]}})
    monkeypatch.setattr(P.C, "PROSP_ZONAS", {"atlanta": [zona]})
    P.cmd_buscar(confirmar=False)
    assert a.arrancadas == [] and P.zona_hecha("atlanta", zona)


def test_zona_vacia_se_reintenta_escrita_distinto_y_despues_se_saltea(buscar, monkeypatch):
    zona = "Midtown, Atlanta, Georgia, USA"
    vacia = {zona: [], "Midtown Atlanta, Georgia, USA": []}
    monkeypatch.setattr(P.C, "PROSP_ZONAS", {"atlanta": [zona]})
    for intento in range(3):
        api = ApifyFalso(libre=5, items_por_zona=vacia)
        con_cuentas(monkeypatch, t1=api)
        P.cmd_buscar(confirmar=False)
        if intento == 0:
            assert api.arrancadas == [zona]
        elif intento == 1:
            assert api.arrancadas == ["Midtown Atlanta, Georgia, USA"]
        else:
            assert api.arrancadas == []                                   # dos veces vacía: se saltea


def test_buscar_sin_poder_leer_el_credito(buscar, monkeypatch):
    api = ApifyFalso()
    api.credito = lambda: (None, None)
    con_cuentas(monkeypatch, t1=api)
    with pytest.raises(SystemExit):                                 # ninguna cuenta responde: frena con error
        P.cmd_buscar(confirmar=False)
    assert api.arrancadas == []


# --- migración y archivos comprimidos ------------------------------------------------
def test_migrar_desde_datos(tmp_path, monkeypatch):
    usar_carpeta(monkeypatch, tmp_path)
    viejo = tmp_path / "datos"
    (viejo / "prospeccion" / "crudo").mkdir(parents=True)
    (viejo / "crudo").mkdir(parents=True)
    (viejo / "prospeccion" / "crudo" / "atlanta__midtown.json").write_text(json.dumps({"items": [{"title": "X"}]}))
    (viejo / "crudo" / "atlanta.json").write_text(json.dumps({"items": [{"title": "Y"}]}))
    (viejo / "prospeccion" / "zonas.json").write_text(json.dumps({"atlanta|Midtown": {"hecha": True}}))
    (viejo / "emails.json").write_text(json.dumps({"x-x.com": {"email": "a@x-x.com"}}))
    (viejo / "mx.json").write_text("roto{")
    assert P.cmd_migrar() == 4                                      # el mx roto se saltea
    assert P.leer_json(P.CRUDO_P / "atlanta__midtown.json.gz", {})["items"][0]["title"] == "X"
    assert P.leer_json(P.CRUDO / "atlanta.json.gz", {})["items"][0]["title"] == "Y"
    assert P.cmd_migrar() == 0                                      # repetirlo no pisa nada


def test_comprimido_igual_para_los_mismos_datos(tmp_path):
    a, b = tmp_path / "a.json.gz", tmp_path / "b.json.gz"
    P.guardar_json(a, {"x": "ñandú", "n": [1, 2]})
    P.guardar_json(b, {"x": "ñandú", "n": [1, 2]})
    assert a.read_bytes() == b.read_bytes() and P.leer_json(a, None) == {"x": "ñandú", "n": [1, 2]}
    assert P.leer_json(tmp_path / "no-existe.json.gz", "def") == "def"


# --- configuración de las ciudades --------------------------------------------------
def test_ciudades_bien_configuradas():
    import campana
    for ciudad, zonas in C.PROSP_ZONAS.items():
        assert ciudad in C.TODAS_CIUDADES, ciudad
        nombre = C.TODAS_CIUDADES[ciudad]["nombre"]
        zona_horaria = campana.zona_ciudad(nombre)
        assert any(k in nombre.lower() for k in C.ZONAS_CIUDAD), f"{nombre} sin zona horaria"
        assert zona_horaria in campana._DESFASE_INVIERNO
        assert len(zonas) == len(set(zonas)), f"zonas repetidas en {ciudad}"
        assert all(z.endswith(", USA") and z.count(",") >= 2 for z in zonas)
    archivos = [P.archivo_zona(c, z).name for c, z in P.zonas_en_orden()]
    assert len(archivos) == len(set(archivos))
    assert campana.zona_ciudad("Phoenix, AZ") == "America/Phoenix"
    assert campana.zona_ciudad("Las Vegas, NV") == "America/Los_Angeles"


def test_subir_con_git_real_aunque_falte_la_lista(tmp_path, monkeypatch):
    """El avance se sube aunque todavía no exista prospectos_todos.csv, y aunque otro haya subido algo antes."""
    import subprocess as sp

    def g(cwd, *a):
        sp.run(["git", *a], cwd=cwd, check=True, capture_output=True)
    remoto, a, b = tmp_path / "remoto.git", tmp_path / "a", tmp_path / "b"
    g(tmp_path, "init", "-q", "--bare", "-b", "main", str(remoto))
    for d in (a, b):
        g(tmp_path, "clone", "-q", str(remoto), str(d))
        g(d, "config", "user.email", "x@x-x.com")
        g(d, "config", "user.name", "x")
        g(d, "config", "pull.rebase", "true")
    (a / "campana").mkdir()
    (a / "campana" / "registro.json").write_text("{}")
    g(a, "add", "-A")
    g(a, "commit", "-qm", "init")
    g(a, "push", "-q", "-u", "origin", "HEAD:main")
    g(b, "pull", "-q", "origin", "main")
    g(b, "branch", "-q", "-u", "origin/main")
    (a / "campana" / "registro.json").write_text('{"x": 1}')                # "el envío" sube algo
    g(a, "commit", "-qam", "envio")
    g(a, "push", "-q")
    usar_carpeta(monkeypatch, tmp_path)
    monkeypatch.setattr(P, "SALIDA", b)
    P.guardar_json(b / "prospeccion" / "zonas.json", {"z": {"hecha": True}})
    assert P.subir("Prospección: prueba")
    g(a, "pull", "-q")
    assert (a / "prospeccion" / "zonas.json").exists() and (a / "campana" / "registro.json").read_text() == '{"x": 1}'
