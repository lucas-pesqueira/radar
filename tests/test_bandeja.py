"""Tests de la lectura de la bandeja (datos inventados)."""
import base64
import json
from datetime import datetime, timezone

import pytest

from test_campana import camp, tanda, reg, registro_enviado  # noqa: F401  (fixture y ayudas)
from ayudas import GmailFalso


def correo(mid, remitente, asunto, cuerpo, **cab):
    data = base64.urlsafe_b64encode(cuerpo.encode()).decode().rstrip("=")
    headers = [{"name": "From", "value": remitente}, {"name": "Subject", "value": asunto}]
    headers += [{"name": k.replace("_", "-"), "value": v} for k, v in cab.items()]
    return {"id": mid, "snippet": cuerpo[:80],
            "payload": {"mimeType": "multipart/alternative", "headers": headers,
                        "parts": [{"mimeType": "text/plain", "body": {"data": data}}]}}


@pytest.fixture
def env(camp, monkeypatch):
    import importlib
    import bandeja as B
    import enviar as E
    importlib.reload(B)
    importlib.reload(E)
    monkeypatch.setattr(B, "K", camp)
    monkeypatch.setattr(E, "K", camp)
    monkeypatch.setattr(E, "B", B)
    monkeypatch.setattr(camp.C, "CONFIRMAR_AL_DIA_SIGUIENTE", False)
    import control as X
    importlib.reload(X)
    monkeypatch.setattr(X, "K", camp)
    monkeypatch.setattr(E, "X", X)
    monkeypatch.setattr(GmailFalso, "REGISTRO", camp.REGISTRO)
    monkeypatch.setenv("RADAR_FECHA", "2026-12-01")
    camp.REGISTRO.write_text(json.dumps({
        "dueno@pizzas-x.com": registro_enviado("2026-11-24"),
        "info@mudanzas-x.com": registro_enviado("2026-11-24"),
        "hola@unas-x.com": registro_enviado("2026-11-24"),
        "contacto@gmail.com": registro_enviado("2026-11-24"),
    }))
    return E, B


def revisar(E, g):
    return E.revisar_bandeja(g, "2026-12-01")


def estado(camp, e):
    return reg(camp)[e]["estado"]


def bajas(camp):
    return json.loads(camp.BAJAS.read_text())


# --- clasificación ----------------------------------------------------------
def test_respuesta_interesada_marca_respondio(camp, env):
    E, B = env
    g = GmailFalso(bandeja=[correo("1", "Juan <dueno@pizzas-x.com>", "Re: X's Google reviews",
                           "Yes, send me the details please.\n\nOn Mon, Lucas wrote:\n> Reply \"no\" and I won't email you again.")])
    marcas, _ = revisar(E, g)
    assert [(m[0], m[1]) for m in marcas] == [("dueno@pizzas-x.com", "respondió")]
    assert estado(camp, "dueno@pizzas-x.com") == "respondió"
    assert bajas(camp) == []


@pytest.mark.parametrize("texto", ["No", "no.", "Not interested, thanks", "Please remove me from your list",
                                   "unsubscribe", "Stop emailing us", "No thank you"])
def test_pedido_de_baja(camp, env, texto):
    E, B = env
    g = GmailFalso(bandeja=[correo("1", "dueno@pizzas-x.com", "Re: X's Google reviews",
                           texto + "\n\nOn Mon, Nov 30, Lucas wrote:\n> If it sounds interesting, just reply \"yes\"")])
    revisar(E, g)
    assert estado(camp, "dueno@pizzas-x.com") == "baja"
    assert "dueno@pizzas-x.com" in bajas(camp)


def test_el_no_de_la_firma_citada_no_es_baja(camp, env):
    E, B = env
    g = GmailFalso(bandeja=[correo("1", "dueno@pizzas-x.com", "Re: X's Google reviews",
                           "How much for two locations?\n\n> Reply \"no\" and I won't email you again.")])
    revisar(E, g)
    assert estado(camp, "dueno@pizzas-x.com") == "respondió"


def test_otra_persona_de_la_empresa(camp, env):
    E, B = env
    g = GmailFalso(bandeja=[correo("1", "gerente@mudanzas-x.com", "Re: X's Google reviews", "Remove us please")])
    revisar(E, g)
    assert estado(camp, "info@mudanzas-x.com") == "baja"
    assert {"info@mudanzas-x.com", "gerente@mudanzas-x.com"} <= set(bajas(camp))


def test_dominio_gratuito_no_se_mezcla(camp, env):
    E, B = env
    g = GmailFalso(bandeja=[correo("1", "otro@gmail.com", "hola", "No")])
    marcas, _ = revisar(E, g)
    assert not marcas and estado(camp, "contacto@gmail.com") == "enviado"


@pytest.mark.parametrize("asunto,cab", [
    ("Automatic reply: X's Google reviews", {}),
    ("Out of Office", {}),
    ("Re: X's Google reviews", {"Auto_Submitted": "auto-replied"}),
    ("Re: X's Google reviews", {"X_Autoreply": "yes"}),
])
def test_respuesta_automatica_se_ignora(camp, env, asunto, cab):
    E, B = env
    g = GmailFalso(bandeja=[correo("1", "hola@unas-x.com", asunto, "I'm out until Monday. No access to email.", **cab)])
    marcas, _ = revisar(E, g)
    assert not marcas and estado(camp, "hola@unas-x.com") == "enviado"


def test_rebote(camp, env):
    E, B = env
    g = GmailFalso(bandeja=[correo("1", "Mail Delivery Subsystem <mailer-daemon@googlemail.com>",
                           "Delivery Status Notification (Failure)",
                           "Address not found\nYour message wasn't delivered to hola@unas-x.com because the address "
                           "couldn't be found.", X_Failed_Recipients="hola@unas-x.com")])
    revisar(E, g)
    assert estado(camp, "hola@unas-x.com") == "rebotó"
    assert estado(camp, "dueno@pizzas-x.com") == "enviado"


def test_demora_no_es_rebote(camp, env):
    E, B = env
    g = GmailFalso(bandeja=[correo("1", "mailer-daemon@googlemail.com", "Delivery Status Notification (Delay)",
                           "Message to hola@unas-x.com has not yet been delivered. Gmail will retry.")])
    marcas, _ = revisar(E, g)
    assert not marcas and estado(camp, "hola@unas-x.com") == "enviado"


def test_mails_ajenos_se_ignoran(camp, env):
    E, B = env
    g = GmailFalso(bandeja=[correo("1", "noreply-dmarc-support@google.com", "Report domain", "xml"),
                    correo("2", "news@tienda.com", "Ofertas", "No te lo pierdas")])
    marcas, vistos = revisar(E, g)
    assert not marcas and len(vistos) == 2


# --- reglas del registro ----------------------------------------------------
def test_nunca_baja_de_nivel(camp, env):
    E, B = env
    g = GmailFalso(bandeja=[correo("1", "dueno@pizzas-x.com", "Re", "No")])
    revisar(E, g)
    g.bandeja.append(correo("2", "dueno@pizzas-x.com", "Re", "Actually, how does it work?"))
    revisar(E, g)
    assert estado(camp, "dueno@pizzas-x.com") == "baja"


def test_cada_mail_se_lee_una_sola_vez(camp, env):
    E, B = env
    g = GmailFalso(bandeja=[correo("1", "dueno@pizzas-x.com", "Re", "Tell me more")])
    revisar(E, g)
    revisar(E, g)
    assert g.leidos == ["1"]


def test_sin_permiso_de_lectura_sigue_mandando(camp, env):
    E, B = env

    class SinPermiso(GmailFalso):
        def ids_bandeja(self, consulta):
            raise E.ErrorGmail("Gmail respondió 403 en /messages: insufficient scopes")

    assert revisar(E, SinPermiso()) == ([], [])


# --- integración con el envío -----------------------------------------------
def test_respuesta_de_la_manana_frena_el_seguimiento(camp, env, monkeypatch):
    E, B = env
    t = tanda(camp, monkeypatch, "2026-12-01", limite=4)
    seg = [i for i in t["items"] if i["tipo"] == "seguimiento 1"]
    assert seg
    quien = seg[0]["email"]
    g = GmailFalso(bandeja=[correo("1", quien, "Re: X's Google reviews", "Please stop")],
                   borradores={f"d{i}": (it["email"], it.get("asunto") or f"{it['negocio']}'s Google reviews")
                    for i, it in enumerate(t["items"])})
    revisar(E, g)
    fin = datetime(2026, 12, 1, 23, 0, tzinfo=timezone.utc)
    enviados, problemas = E.enviar(ahora=fin, gmail=g)
    assert quien not in g.mandados and quien not in enviados
    assert estado(camp, quien) == "baja"
    assert not problemas


def test_texto_html_y_cita():
    import bandeja as B
    msg = {"payload": {"mimeType": "text/html", "headers": [],
                       "body": {"data": base64.urlsafe_b64encode(b"<p>Hi</p><p>Count me in</p>").decode()}}}
    assert "Count me in" in B.texto_de(msg["payload"])
    assert B.respuesta_nueva("Sure!\nOn Tue, Dec 1, 2026 Lucas wrote:\n> no") == "Sure!"
