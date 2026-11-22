"""Tests de los controles: calidad de borradores, freno, alertas, métricas y diario (datos inventados)."""
import json
from datetime import datetime, timezone

import pytest

from test_campana import camp, tanda, reg, registro_enviado  # noqa: F401  (fixture y ayudas)
from ayudas import GmailFalso, texto_bien


@pytest.fixture
def X(camp, monkeypatch):
    import importlib
    import control
    importlib.reload(control)
    monkeypatch.setattr(control, "K", camp)
    monkeypatch.setattr(control.C, "FRENO_DESDE", "2026-11-01")
    return control


@pytest.fixture
def env(camp, X, monkeypatch):
    import importlib
    import enviar as E
    importlib.reload(E)
    monkeypatch.setattr(E, "K", camp)
    monkeypatch.setattr(E, "X", X)
    monkeypatch.setattr(camp.C, "CONFIRMAR_AL_DIA_SIGUIENTE", False)
    monkeypatch.setattr(GmailFalso, "REGISTRO", camp.REGISTRO)
    return E


R = {"negocio": "Pizzas Mario", "precio": 59, "asunto": "Pizzas Mario's Google reviews"}
FIN = datetime(2026, 11, 30, 23, 0, tzinfo=timezone.utc)


# --- calidad del borrador ---------------------------------------------------
@pytest.mark.parametrize("tipo", ["primer mail", "seguimiento 1", "seguimiento 2"])
def test_borrador_correcto_pasa(X, tipo):
    asunto = "Pizzas Mario's Google reviews" if tipo == "primer mail" else "Re: Pizzas Mario's Google reviews"
    assert X.revisar_borrador(texto_bien("Pizzas Mario", 59, tipo), asunto, R, tipo) == []


@pytest.mark.parametrize("cambio,falla", [
    (lambda t: t.replace("Monseñor Piaggio 55", ""), "dirección"),
    (lambda t: t.replace("Reply \"no\" and I won't email you again.", ""), "baja"),
    (lambda t: t.replace("Lucas Pesqueira · Tinko Projects", "Lucas"), "firma"),
    (lambda t: t.replace("$59/month", "$99/month"), "precio"),
    (lambda t: t.replace("No contract.", "No contract. See https://tinkoprojects.com."), "links"),
    (lambda t: t.replace("Hi Pizzas Mario team", "Hi [negocio] team"), "plantilla"),
    (lambda t: t.replace("Pizzas Mario", "Otro Negocio"), "negocio"),
    (lambda t: t[:200], "largo"),
])
def test_borrador_con_errores_no_pasa(X, cambio, falla):
    texto = cambio(texto_bien("Pizzas Mario", 59, "primer mail"))
    problemas = X.revisar_borrador(texto, "Pizzas Mario's Google reviews", R, "primer mail")
    assert problemas and any(falla in p for p in problemas), problemas


def test_asunto_equivocado(X):
    p = X.revisar_borrador(texto_bien("Pizzas Mario", 59, "primer mail"), "Hola", R, "primer mail")
    assert any("asunto" in x for x in p)


def test_seguimiento_2_con_descuento_equivocado(X):
    t = texto_bien("Pizzas Mario", 59, "seguimiento 2").replace("$29/month", "$49/month")
    p = X.revisar_borrador(t, "Re: Pizzas Mario's Google reviews", R, "seguimiento 2")
    assert any("descuento" in x for x in p)


def test_la_cita_del_mail_anterior_no_cuenta(X):
    """En los seguimientos, lo citado de abajo (con otros montos o links) no se revisa."""
    t = texto_bien("Pizzas Mario", 59, "seguimiento 1") + "\n> visit https://otro.com for $5000"
    assert X.revisar_borrador(t, "Re: Pizzas Mario's Google reviews", R, "seguimiento 1") == []


def test_borrador_que_falla_no_sale(camp, env, monkeypatch):
    items = tanda(camp, monkeypatch, "2026-11-30", limite=3)["items"]
    malo = items[0]
    b = {f"d{i}": (it["email"], f"{it['negocio']}'s Google reviews") for i, it in enumerate(items)}
    b["d0"] = (malo["email"], f"{malo['negocio']}'s Google reviews", "Hola, esto está cortado")
    g = GmailFalso(b)
    env.enviar(ahora=FIN, gmail=g)
    assert malo["email"] not in g.mandados and len(g.mandados) == 2
    assert reg(camp)[malo["email"]]["estado"] == "armado"


def test_borrador_que_falla_avisa(camp, env, monkeypatch, X):
    items = tanda(camp, monkeypatch, "2026-11-30", limite=1)["items"]
    it = items[0]
    g = GmailFalso({"d": (it["email"], f"{it['negocio']}'s Google reviews", "texto roto")})
    t = datetime.fromisoformat(it["envio_utc"])
    _, problemas = env.enviar(ahora=t, gmail=g)
    assert problemas and "control" in problemas[0][1]
    assert X.leer_diario()["2026-11-30"]["no_salieron"][0]["email"] == it["email"]


# --- freno de emergencia ----------------------------------------------------
def rebotados(n, total=30, dia="2026-11-25"):
    r = {}
    for i in range(total):
        e = f"p{i}@neg{i}-x.com"
        r[e] = registro_enviado(dia, "rebotó" if i < n else "enviado")
    return r


def test_freno_por_rebotes(camp, X):
    assert X.evaluar_freno(rebotados(2), "2026-11-30") is None
    assert "3 rebotes" in X.evaluar_freno(rebotados(3), "2026-11-30")


def test_freno_cuenta_desde_la_fecha_de_arranque(camp, X, monkeypatch):
    monkeypatch.setattr(X.C, "FRENO_DESDE", "2026-11-26")
    assert X.evaluar_freno(rebotados(5, dia="2026-11-20"), "2026-11-30") is None


def test_freno_por_bajas_en_el_dia(camp, X):
    r = rebotados(0, total=5)
    for e in list(r)[:3]:
        r[e]["estado"] = "baja"
        r[e]["fechas"]["baja"] = "2026-11-30"
    assert "3 bajas" in X.evaluar_freno(r, "2026-11-30")
    assert X.evaluar_freno(r, "2026-12-01") is None


def test_freno_se_activa_una_vez_y_se_destraba(camp, X):
    r = rebotados(3)
    assert X.activar_freno(r, "2026-11-30")
    assert X.activar_freno(r, "2026-11-30") is None                   # no avisa dos veces
    assert X.freno_activo()
    assert X.destrabar("2026-11-30")
    assert not X.freno_activo()
    assert X.evaluar_freno(r, "2026-11-30") is None                   # lo viejo ya no cuenta


def test_tanda_con_freno_solo_seguimientos(camp, X, monkeypatch):
    camp.REGISTRO.write_text(json.dumps({"a@a.com": registro_enviado("2026-11-23")}))
    X.K.guardar_json(X.ruta("freno.json"), {"activo": True, "motivo": "prueba", "desde": "2026-11-27"})
    t = tanda(camp, monkeypatch, "2026-11-30", limite=10)
    assert [i["tipo"] for i in t["items"]] == ["seguimiento 1"]


def test_envio_con_freno_no_manda_primeros_mails(camp, env, X, monkeypatch):
    camp.REGISTRO.write_text(json.dumps({"a@a.com": registro_enviado("2026-11-23")}))
    items = tanda(camp, monkeypatch, "2026-11-30", limite=4)["items"]
    X.K.guardar_json(X.ruta("freno.json"), {"activo": True, "motivo": "prueba", "desde": "2026-11-30"})
    b = {f"d{i}": (it["email"], it.get("asunto") or f"{it['negocio']}'s Google reviews")
         for i, it in enumerate(items)}
    g = GmailFalso(b)
    env.enviar(ahora=FIN, gmail=g)
    assert g.mandados == ["a@a.com"]


# --- métricas, alertas y diario -----------------------------------------------
def test_metricas(camp, X):
    r = {
        "a@a-x.com": registro_enviado("2026-11-24", "respondió", **{"respondió": "2026-11-25"}),
        "b@b-x.com": registro_enviado("2026-11-24", "seguimiento 2", **{"seguimiento 1": "2026-11-27",
                                                                        "seguimiento 2": "2026-12-03"}),
        "c@c-x.com": registro_enviado("2026-11-24", "rebotó"),
        "d@d-x.com": {**registro_enviado("2026-11-24", "armado")},
    }
    m = X.calcular(r, set(), "2026-12-03")
    assert m["total"]["contactados"] == 3                           # el armado no cuenta
    assert m["total"]["respondieron"] == 1 and m["total"]["rebotes"] == 1
    assert m["total"]["secuencia_completa"] == 1
    assert m["respuestas_por_mail"] == {"tras primer mail": 1}
    assert m["stock_sin_contactar"]["A"] + m["stock_sin_contactar"]["B"] + m["stock_sin_contactar"]["C"] == 120


def test_metricas_no_reescribe_si_no_cambio(camp, X):
    X.actualizar({}, set(), "2026-11-30")
    antes = X.ruta("metricas.json").read_text()
    X.actualizar({}, set(), "2026-11-30")
    assert X.ruta("metricas.json").read_text() == antes


def test_alerta_stock_bajo(camp, X, monkeypatch):
    monkeypatch.setattr(X.C, "ALERTA_STOCK_AB", 10_000)
    assert any("prospectos A/B" in a for a in X.calcular({}, set(), "2026-11-30")["alertas"])


def test_alerta_credito_y_tanda_corta(camp, X):
    X.anotar_tanda("2026-11-30", {"fecha": "2026-11-30", "nuevos": 4, "cupo_nuevos": 20,
                                  "gasto_estimado": 1.0, "credito_libre": 2.0})
    al = X.calcular({}, set(), "2026-11-30")["alertas"]
    assert any("crédito de Apify" in a for a in al) and any("solo 4 primeros" in a for a in al)


def test_tanda_queda_en_el_diario(camp, X, monkeypatch):
    tanda(camp, monkeypatch, "2026-11-30", limite=5)
    d = X.leer_diario()["2026-11-30"]["tanda"]
    assert d["nuevos"] == 5 and d["rondas"] >= 1 and d["gasto_estimado"] >= 0.5
    assert X.ruta("metricas.json").exists()


def test_envio_queda_en_el_diario(camp, env, X, monkeypatch):
    items = tanda(camp, monkeypatch, "2026-11-30", limite=3)["items"]
    g = GmailFalso({f"d{i}": (it["email"], f"{it['negocio']}'s Google reviews") for i, it in enumerate(items)})
    env.enviar(ahora=FIN, gmail=g)
    env.enviar(ahora=FIN, gmail=g)
    assert len(X.leer_diario()["2026-11-30"]["enviados"]) == 3


def test_diario_borra_lo_viejo(camp, X):
    X.anotar("2026-01-01", "enviados", {"email": "a@a.com"}, "email")
    X.anotar("2026-11-30", "enviados", {"email": "b@b.com"}, "email")
    assert list(X.leer_diario()) == ["2026-11-30"]


def test_lineas_cortadas_por_gmail(X):
    """Gmail corta el texto plano cada ~76 caracteres: la firma o el nombre pueden quedar partidos."""
    t = texto_bien("Pizzas Mario", 59, "primer mail").replace("Tinko Projects", "Tinko\nProjects")
    t = t.replace("Hi Pizzas Mario team", "Hi Pizzas\nMario team").replace("Piaggio 55", "Piaggio\n55")
    assert X.revisar_borrador(t, "Pizzas Mario's Google reviews", R, "primer mail") == []


def test_mail_real_de_la_campana_pasa(X):
    """Formato tal cual sale de Gmail (texto plano cortado), con datos inventados."""
    t = ("Hi Pace Bistro team,\n\nAlex's 5-star review from November 16 is still waiting for a reply, and 4\n"
         "of your 5 most recent reviews are the same. So I wrote a reply you can copy\nand paste:\n\n"
         "To Alex: \"Hi Alex, thanks for coming in. Glad the risotto was a hit.\"\n\nIt's yours either way, "
         "no strings attached.\n\nI'm Lucas, and I write review replies for local restaurants. If you'd like,\n"
         "I'll reply to all your unanswered reviews from the last 30 days for free,\nand you approve each one "
         "before it goes live. After that it's $59/month to\nkeep up with every new review. No contract.\n\n"
         "Want me to do it? Just reply \"yes\".\n\nLucas\n\nLucas Pesqueira \u00b7 Tinko Projects\n"
         "Monse\u00f1or Piaggio 55, Avellaneda (1870), Buenos Aires, Argentina \u00b7 Reply\n"
         "\"no\" and I won't email you again.")
    r = {"negocio": "Pace Bistro", "precio": 59}
    assert X.revisar_borrador(t, "Pace Bistro's Google reviews", r, "primer mail") == []


def test_plantillas_nuevas(X):
    """22/11/2026: seguimiento 1 sin precio, saludo con el nombre corto, sin frases gastadas,
    y el primer mail tiene que ofrecer la prueba gratis."""
    from tests.ayudas import texto_bien
    r = {"negocio": "Citiside Property Management", "negocio_corto": "Citiside", "precio": 99,
         "asunto": "Citiside Property Management's Google reviews"}
    for tipo in ("primer mail", "seguimiento 1", "seguimiento 2"):
        t = texto_bien("Citiside", 99, tipo)
        assert X.revisar_borrador(t, r["asunto"], r, tipo) == [], tipo
    viejo = texto_bien("Citiside", 99, "primer mail").replace("Hi Citiside team,", "Hi Citiside team,\n\nMy name is Lucas.")
    assert any("gastadas" in p for p in X.revisar_borrador(viejo, r["asunto"], r, "primer mail"))
    sin_free = texto_bien("Citiside", 99, "primer mail").replace("for free", "for a while")
    assert any("gratis" in p for p in X.revisar_borrador(sin_free, r["asunto"], r, "primer mail"))
    seg1_mal = texto_bien("Citiside", 99, "seguimiento 1").replace("for free", "for $59")
    assert any("montos" in p for p in X.revisar_borrador(seg1_mal, r["asunto"], r, "seguimiento 1"))


@pytest.mark.parametrize("largo,corto", [
    ("Citiside Property Management", "Citiside"),
    ("Wirks Moving and Storage", "Wirks"),
    ("Excalibur Moving & Storage", "Excalibur"),
    ("Five Star Movers", "Five Star"),
    ("Yale Management Services", "Yale"),
    ("Property Management", "Property Management"),        # no deja vacío
    ("Luigi's Pizzeria", "Luigi's Pizzeria"),
    ("Luxury Nails & Spa", "Luxury Nails & Spa"),
])
def test_nombre_corto(largo, corto):
    import campana as K
    assert K.nombre_corto(largo) == corto
