"""Tests de escribir.py (borradores automáticos) con datos inventados."""
import json
from datetime import date

import pytest

from test_campana import camp, tanda, reg  # noqa: F401
from ayudas import GmailFalso

HOY = date(2026, 11, 30)


@pytest.fixture
def W(camp, monkeypatch):
    import importlib
    import escribir as W
    importlib.reload(W)
    monkeypatch.setattr(W, "K", camp)
    import control as X
    importlib.reload(X)
    monkeypatch.setattr(X, "K", camp)
    monkeypatch.setattr(W, "X", X)
    return W


def item(**kw):
    base = {"tipo": "primer mail", "email": "info@neg-x.com", "negocio": "Pace Bistro", "rubro": "Restaurantes independientes",
            "precio": 59, "ciudad": "Los Angeles, CA", "prioridad": "A", "sin_responder": 4, "de_las_ultimas": 5,
            "resenas": [{"autor": "Ana", "estrellas": 2, "fecha": "2026-11-20", "texto": "Slow service"},
                        {"autor": "Bob", "estrellas": 5, "fecha": "2026-11-18", "texto": "Great pasta"}]}
    base.update(kw)
    return base


def resp(it, n=2):
    return [(r, f"Hi {r['autor']}, thanks for coming in.") for r in it["resenas"][:n]]


class TestPrimerMail:
    def test_pasa_el_control(self, W):
        it = item()
        asunto, t = W.primer_mail(it, resp(it), HOY)
        assert asunto == "Pace Bistro's Google reviews"
        assert W.X.revisar_borrador(t, asunto, it, "primer mail") == []
        assert "Ana's 2-star review from November 20 is still waiting" in t and W.NEGATIVA in t
        assert "4 of your 5 most recent reviews are the same" in t and "last 30 days" in t
        assert 'To Bob: "Hi Bob' in t and "They're yours" in t

    def test_variantes(self, W):
        it = item(sin_responder=5, resenas=[{"autor": "", "estrellas": 5, "fecha": "2026-09-01", "texto": "x"}],
                  negocio="Citiside Property Management", rubro="Administradoras de alquileres", precio=99,
                  en_espanol=True)
        asunto, t = W.primer_mail(it, [(it["resenas"][0], "Thank you.")], HOY)
        assert t.startswith("Hi Citiside team,") and "A 5-star review from September 1" in t
        assert "none of your 5 most recent reviews have a reply either" in t and "last 90 days" in t
        assert 'To the 5-star review: "Thank you."' in t and "It's yours" in t and W.NEGATIVA not in t
        assert "in Spanish" in t and "property management companies" in t
        assert W.X.revisar_borrador(t, asunto, {"negocio": it["negocio"], "precio": 99}, "primer mail") == []

    def test_una_sola_sin_responder_y_prioridad_c(self, W):
        it = item(sin_responder=1, prioridad="C")
        _, t = W.primer_mail(it, resp(it, 1), HOY)
        assert "Ana's 2-star review is still waiting for a reply." in t


class TestSeguimientos:
    def test_nombres_del_hilo(self, W):
        txt = 'Hi team,\n\nTo Ray: "Hi Ray, thanks"\n\nTo the 4-star\nreview: "Thank you"\n> To Zed: "x"'
        assert W.nombres_del_hilo(txt) == ["Ray", "your 4-star review"]
        assert W.dias_del_hilo("from the last 90\ndays for free") == 90

    @pytest.mark.parametrize("nombres,frase", [(["Ray", "Sue"], "replies for Ray and Sue"),
                                               (["Ray"], "reply for Ray"), ([], "replies I wrote")])
    def test_seguimiento_1(self, W, nombres, frase):
        t = W.seguimiento_1(nombres)
        assert frase in t
        r = {"negocio": "Pace Bistro", "precio": 59, "asunto": "Pace Bistro's Google reviews"}
        assert W.X.revisar_borrador(t, r["asunto"], r, "seguimiento 1") == []

    def test_seguimiento_2_nombre_corto_y_descuento(self, W):
        it = item(tipo="seguimiento 2", negocio="Shannon Property Management", rubro="Administradoras de alquileres",
                  precio=99, asunto="Shannon Property Management's Google reviews")
        t = W.seguimiento_2(it, HOY)
        assert t.startswith("Hi Shannon team,") and "$49/month" in t and "property managers" in t
        assert "holidays" in t and "everything" in W.seguimiento_2(it, date(2027, 2, 1))
        r = {"negocio": it["negocio"], "precio": 99, "asunto": it["asunto"]}   # como en el registro
        assert W.X.revisar_borrador(t, it["asunto"], r, "seguimiento 2") == []


def test_primer_mail_con_competencia(W):
    it = item(comp_responden=3, comp_de=5, comp_ejemplo="Uno Grill")
    asunto, t = W.primer_mail(it, [({"autor": "Ana", "estrellas": 5, "fecha": "2026-11-20"}, "Thanks, Ana!")], HOY)
    assert "3 of the 5 restaurants closest to you on Google Maps answer their reviews, including Uno Grill." in t
    r = {"negocio": it["negocio"], "precio": it["precio"], "asunto": asunto}
    assert W.X.revisar_borrador(t, asunto, r, "primer mail") == []
    _, sin = W.primer_mail(item(), [({"autor": "Ana", "estrellas": 5, "fecha": "2026-11-20"}, "Thanks, Ana!")], HOY)
    assert "closest to you" not in sin


def test_seguimiento_3_corto_sin_precio_y_pasa_el_control(W):
    it = item(tipo="seguimiento 3", negocio="Shannon Property Management", rubro="Administradoras de alquileres",
              precio=99, asunto="Shannon Property Management's Google reviews")
    t = W.seguimiento_3(it)
    assert t.startswith("Hi Shannon team,") and "last email" in t and "$" not in t
    r = {"negocio": it["negocio"], "precio": 99, "asunto": it["asunto"]}
    assert W.X.revisar_borrador(t, it["asunto"], r, "seguimiento 3") == []


def test_seguimiento_2_ya_no_promete_ser_el_ultimo(W):
    it = item(tipo="seguimiento 2", negocio="Pace Bistro", precio=59, asunto="Pace Bistro's Google reviews")
    t = W.seguimiento_2(it, HOY).lower()
    assert "last note" not in t and "won't write again" not in t.split("lucas pesqueira")[0]


class SesionFalsa:
    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.pedidos = []

    def post(self, url, **kw):
        self.pedidos.append(kw["json"])
        codigo, cuerpo = self.respuestas.pop(0)

        class R:
            status_code = codigo
            text = json.dumps(cuerpo)

            def json(self):
                return cuerpo
        return R()


def contenido(d):
    return {"content": [{"type": "text", "text": json.dumps(d)}]}


class TestIA:
    def test_respuestas_y_salteadas(self, W, monkeypatch):
        monkeypatch.setattr(W.time, "sleep", lambda s: None)
        s = SesionFalsa([(529, {}), (200, contenido({"replies": [{"n": 1, "reply": 'Hi Bob, "great" to see you.'}],
                                                     "skipped": [{"n": 0, "reason": "theft"}]}))])
        out = W.pedir_respuestas(item(), clave="k", sesion=s)
        assert [r["autor"] for r, _ in out] == ["Bob"] and out[0][1] == "Hi Bob, 'great' to see you."
        assert s.pedidos[-1]["model"] == W.C.MODELO_ESCRITURA

    def test_sin_clave(self, W, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(W.ErrorIA):
            W.pedir_respuestas(item())

    def test_error_de_la_api(self, W):
        with pytest.raises(W.ErrorIA):
            W.pedir_respuestas(item(), clave="k", sesion=SesionFalsa([(401, {"error": "bad key"})]))

    def test_reglas_salen_de_plantillas(self, W, camp):
        (camp.DIR / "plantillas.md").write_text("## X\n### Cómo escribir las respuestas a las reseñas\n1. Regla A\n"
                                                "### Frases\nno", encoding="utf-8")
        assert W.reglas_respuestas() == "1. Regla A"


class GmailConHilos(GmailFalso):
    def __init__(self, *a, hilos=None, **kw):
        super().__init__(*a, **kw)
        self.creados = []
        self.hilos = hilos or {}

    def _pedir(self, metodo, ruta, **kw):
        if metodo == "POST" and ruta == "/drafts":
            self.creados.append(kw["json"]["message"])
            return {"id": f"nuevo{len(self.creados)}"}
        raise AssertionError(ruta)


def test_escribe_solo_lo_que_falta(camp, W, monkeypatch):
    items = tanda(camp, monkeypatch, "2026-11-30", limite=4)["items"]
    ya = items[0]["email"]
    g = GmailConHilos({"d0": (ya, "x")})
    monkeypatch.setattr(W, "hilo_enviado", lambda gm, e: ("hilo1", "<m1@x>", 'To Ray: "hi"'))
    llamadas = []

    def ia(it):
        llamadas.append(it["email"])
        return resp(it) if it.get("resenas") else []
    creados, salteados, problemas = W.escribir(g, "2026-11-30", ia=ia)
    assert ya not in [c[3] for c in creados] and ya not in llamadas
    assert len(creados) + len(salteados) + len(problemas) == len(items) - 1
    assert not problemas, problemas
    assert creados and len(g.creados) == len(creados)
    import base64
    for m in g.creados:
        crudo = base64.urlsafe_b64decode(m['raw']).decode()
        assert 'Content-Type: text/plain' in crudo
    # Segunda corrida (plan B en el envío): no duplica.
    for i, m in enumerate(g.creados):
        g.b[f"n{i}"] = (creados[i][3], "x")
    assert W.escribir(g, "2026-11-30", ia=ia)[0] == []


def test_si_la_ia_falla_sigue_con_el_resto(camp, W, monkeypatch):
    tanda(camp, monkeypatch, "2026-11-30", limite=3)
    g = GmailConHilos()

    def ia(it):
        raise W.ErrorIA("caída")
    creados, _, problemas = W.escribir(g, "2026-11-30", ia=ia)
    assert problemas and all("IA" in m for _, m in problemas)


def test_respetar_bajas(camp, W, monkeypatch):
    items = tanda(camp, monkeypatch, "2026-11-30", limite=2)["items"]
    r = reg(camp)
    r[items[0]["email"]]["estado"] = "baja"
    camp.REGISTRO.write_text(json.dumps(r))
    g = GmailConHilos()
    creados, salteados, _ = W.escribir(g, "2026-11-30", ia=resp)
    assert items[0]["email"] in [e for e, _ in salteados]
