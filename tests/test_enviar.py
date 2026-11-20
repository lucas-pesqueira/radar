"""Tests del envío automático con un Gmail falso (datos inventados)."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from test_campana import camp, tanda, reg, registro_enviado  # noqa: F401  (fixture y ayudas)

ART = timezone(timedelta(hours=-3))


class GmailFalso:
    def __init__(self, borradores):
        self.b = borradores                      # {id: (para, asunto)}
        self.mandados = []

    def borradores(self):
        out = {}
        for did, (para, asunto) in self.b.items():
            out.setdefault(para.lower(), []).append((did, asunto))
        return out

    def mandar(self, did):
        assert did in self.b, "mandó un borrador que no existe"
        self.mandados.append(self.b.pop(did)[0])


@pytest.fixture
def env(camp, monkeypatch):
    import importlib
    import enviar as E
    importlib.reload(E)
    monkeypatch.setattr(E, "K", camp)
    monkeypatch.setattr(camp.C, "CONFIRMAR_AL_DIA_SIGUIENTE", False)
    return E


def armar(camp, monkeypatch, limite=6):
    t = tanda(camp, monkeypatch, "2026-11-30", limite=limite)
    return t["items"]


def borradores_de(items):
    return {f"d{i}": (it["email"], f"{it['negocio']}'s Google reviews") for i, it in enumerate(items)}


def test_manda_solo_lo_que_ya_tiene_hora(camp, env, monkeypatch):
    items = armar(camp, monkeypatch)
    g = GmailFalso(borradores_de(items))
    corte = sorted(datetime.fromisoformat(i["envio_utc"]) for i in items)[2]
    enviados, problemas = env.enviar(ahora=corte, gmail=g)
    assert len(enviados) == 3 and not problemas
    r = reg(camp)
    for e in enviados:
        assert r[e]["estado"] == "enviado" and "armado" not in r[e]
    assert sum(1 for v in r.values() if v.get("armado")) == 3


def test_nunca_manda_dos_veces(camp, env, monkeypatch):
    items = armar(camp, monkeypatch)
    g = GmailFalso(borradores_de(items))
    fin = datetime(2026, 11, 30, 23, 0, tzinfo=timezone.utc)
    env.enviar(ahora=fin, gmail=g)
    env.enviar(ahora=fin, gmail=g)
    assert len(g.mandados) == len(set(g.mandados)) == len(items)


def test_sin_borrador_no_sale_y_avisa_una_vez(camp, env, monkeypatch):
    items = armar(camp, monkeypatch)
    sin = items[0]
    g = GmailFalso({k: v for k, v in borradores_de(items).items() if v[0] != sin["email"]})
    t = datetime.fromisoformat(sin["envio_utc"])
    _, problemas = env.enviar(ahora=t + timedelta(minutes=5), gmail=g)
    assert problemas and problemas[0][0] == sin["email"]
    _, problemas = env.enviar(ahora=t + timedelta(hours=2), gmail=g)
    assert not problemas                                            # no avisa cada 15 minutos
    assert sin["email"] not in g.mandados
    assert reg(camp)[sin["email"]]["estado"] == "armado"


def test_no_manda_a_bajas_ni_respondidos(camp, env, monkeypatch):
    items = armar(camp, monkeypatch)
    g = GmailFalso(borradores_de(items))
    camp.BAJAS.write_text(json.dumps([items[0]["email"]]))
    camp.cmd_marcar(items[1]["email"], "respondió")
    env.enviar(ahora=datetime(2026, 11, 30, 23, 0, tzinfo=timezone.utc), gmail=g)
    assert items[0]["email"] not in g.mandados and items[1]["email"] not in g.mandados


def test_borradores_ajenos_no_se_tocan(camp, env, monkeypatch):
    items = armar(camp, monkeypatch)
    b = borradores_de(items)
    b["mio"] = ("amigo@otro.com", "Hola")
    g = GmailFalso(b)
    env.enviar(ahora=datetime(2026, 11, 30, 23, 0, tzinfo=timezone.utc), gmail=g)
    assert "mio" in g.b


def test_dos_borradores_para_el_mismo_mail(camp, env, monkeypatch):
    items = armar(camp, monkeypatch, limite=1)
    e = items[0]["email"]
    asunto = f"{items[0]['negocio']}'s Google reviews"
    g = GmailFalso({"a": (e, asunto), "b": (e, "Otra cosa")})
    env.enviar(ahora=datetime(2026, 11, 30, 23, 0, tzinfo=timezone.utc), gmail=g)
    assert g.mandados == [e] and "b" in g.b                          # elige el del asunto de la campaña
    g2 = GmailFalso({"a": (e, asunto), "b": (e, "Re: " + asunto)})
    camp.REGISTRO.write_text(json.dumps({e: {**reg(camp)[e], "estado": "armado",
                                             "armado": {"tipo": "primer mail", "fecha": "2026-11-30",
                                                        "envio_utc": items[0]["envio_utc"]}}}))
    env.enviar(ahora=datetime(2026, 11, 30, 23, 0, tzinfo=timezone.utc), gmail=g2)
    assert not g2.mandados                                           # ambiguo: no manda


def test_no_manda_lo_de_otro_dia(camp, env, monkeypatch):
    items = armar(camp, monkeypatch)
    g = GmailFalso(borradores_de(items))
    monkeypatch.setenv("RADAR_FECHA", "2026-12-01")
    env.enviar(ahora=datetime(2026, 12, 1, 23, 0, tzinfo=timezone.utc), gmail=g)
    assert not g.mandados


def test_seguimiento_enviado_queda_registrado(camp, env, monkeypatch):
    camp.REGISTRO.write_text(json.dumps({"a@a.com": registro_enviado("2026-11-16")}))
    items = armar(camp, monkeypatch, limite=1)
    g = GmailFalso({"x": ("a@a.com", "Re: X's Google reviews")})
    env.enviar(ahora=datetime(2026, 11, 30, 23, 0, tzinfo=timezone.utc), gmail=g)
    r = reg(camp)["a@a.com"]
    assert r["estado"] == "seguimiento 1" and r["fechas"]["seguimiento 1"] == "2026-11-30"


def test_lo_que_no_salio_se_libera_al_dia_siguiente(camp, env, monkeypatch):
    camp.REGISTRO.write_text(json.dumps({"a@a.com": registro_enviado("2026-11-16")}))
    items = armar(camp, monkeypatch, limite=3)
    nuevos = [i["email"] for i in items if i["tipo"] == "primer mail"]
    monkeypatch.setenv("RADAR_FECHA", "2026-12-01")
    r = reg(camp)
    camp.confirmar_armados(r)
    assert all(e not in r for e in nuevos)                           # vuelven a estar disponibles
    assert r["a@a.com"]["estado"] == "enviado" and "armado" not in r["a@a.com"]
    assert camp.seguimientos_pendientes(r) == [("a@a.com", 1)]
