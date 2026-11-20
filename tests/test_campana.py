"""Tests de campana.py con datos inventados (este repo es público: nunca usar datos reales acá).

Correr desde la carpeta del repo:  py -m pytest -q
"""
import csv
import importlib
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

RUBROS = ["Administradoras de alquileres", "Mudanzas", "Restaurantes independientes", "Salones de uñas"]
CIUDADES = ["Los Angeles, CA", "Atlanta, GA", "Houston, TX"]
COLUMNAS = ["prioridad", "puntaje", "rubro_nombre", "ciudad_nombre", "nombre", "email", "place_id", "maps"]


def prospectos(n=120):
    out = []
    for i in range(n):
        email = f"info@negocio{i}.com" if i % 5 else f"negocio{i}@gmail.com"
        if i in (10, 11):                     # dos sucursales de la misma empresa
            email = f"local{i}@grupo-x.com"
        out.append({"prioridad": "ABC"[i % 3], "puntaje": str(100 - i), "rubro_nombre": RUBROS[i % 4],
                    "ciudad_nombre": CIUDADES[i % 3], "nombre": f"NEGOCIO NUMERO {i} LLC",
                    "email": email, "place_id": f"ChIJ{i:06d}", "maps": ""})
    return out


@pytest.fixture
def camp(tmp_path, monkeypatch):
    datos = tmp_path / "prospectos"
    (datos / "campana").mkdir(parents=True)
    with (datos / "prospectos_todos.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS)
        w.writeheader()
        w.writerows(prospectos())
    (datos / "campana" / "registro.json").write_text("{}", encoding="utf-8")
    (datos / "campana" / "bajas.json").write_text("[]", encoding="utf-8")
    import campana as c
    importlib.reload(c)
    monkeypatch.setattr(c, "DATOS", datos)
    monkeypatch.setattr(c, "DIR", datos / "campana")
    monkeypatch.setattr(c, "REGISTRO", datos / "campana" / "registro.json")
    monkeypatch.setattr(c, "BAJAS", datos / "campana" / "bajas.json")
    monkeypatch.setattr(c, "TANDAS", datos / "campana" / "tandas")
    monkeypatch.setattr(c, "PROSPECTOS", datos / "prospectos_todos.csv")
    monkeypatch.setattr(c, "BACKUPS", tmp_path / "backups")
    monkeypatch.setattr(c, "lugares_guardados", lambda: {})
    monkeypatch.setattr(c, "token", lambda: "x")
    monkeypatch.setattr(c, "Apify", FakeApify)
    monkeypatch.setattr(c.C, "CONFIRMAR_AL_DIA_SIGUIENTE", True)
    c._respondidos = set()
    c._faltantes = set()
    c._llamadas = []

    def verificar(api, ids):
        c._llamadas.append(list(ids))
        return {pid: lugar(pid, respondida=pid in c._respondidos) for pid in ids if pid not in c._faltantes}
    monkeypatch.setattr(c, "verificar", verificar)
    return c


class FakeApify:
    def __init__(self, tok):
        pass

    def credito(self):
        return (0, 100)


def lugar(pid, respondida=False, cerrado=False):
    ahora = datetime.now(timezone.utc)
    rv = [{"reviewOrigin": "Google", "publishedAtDate": (ahora - timedelta(days=i + 1)).isoformat(),
           "stars": 5 if i else 1, "text": f"Review text {i} about the service" if i else "Terrible service, rude staff",
           "name": f"Ann{i} Smith", "responseFromOwnerText": "Thanks!" if respondida else ""} for i in range(5)]
    return {"placeId": pid, "reviews": rv, "permanentlyClosed": cerrado}


def tanda(c, monkeypatch, dia, limite=20, **kw):
    monkeypatch.setenv("RADAR_FECHA", dia)
    return c.cmd_tanda(limite=limite, **kw)


def reg(c):
    return json.loads(c.REGISTRO.read_text(encoding="utf-8"))


# --- cupo -------------------------------------------------------------------
@pytest.mark.parametrize("frac", [0, 0.3, 0.5, 0.8])
def test_llena_el_cupo_aunque_muchos_ya_respondieron(camp, monkeypatch, frac):
    camp._respondidos = {f"ChIJ{i:06d}" for i in range(120) if i % 10 < frac * 10}
    t = tanda(camp, monkeypatch, "2026-11-30", limite=25)
    sucursales = {"ChIJ000010", "ChIJ000011"} - camp._respondidos
    buenos = 120 - len(camp._respondidos) - (1 if len(sucursales) == 2 else 0)  # una sola sucursal por empresa
    assert len(t["items"]) == min(25, buenos)
    assert len(camp._llamadas) <= 3


def test_llena_el_cupo_si_maps_no_devuelve_algunos(camp, monkeypatch):
    camp._faltantes = {f"ChIJ{i:06d}" for i in range(0, 120, 3)}
    t = tanda(camp, monkeypatch, "2026-11-30", limite=25)
    assert len(t["items"]) == 25
    assert all(i["verificado"] for i in t["items"])


def test_no_pasa_el_maximo_de_rondas(camp, monkeypatch):
    camp._respondidos = {f"ChIJ{i:06d}" for i in range(120)}       # nadie sirve
    t = tanda(camp, monkeypatch, "2026-11-30", limite=25)
    assert len(t["items"]) == 0
    assert 1 <= len(camp._llamadas) <= camp.C.VERIFICAR_RONDAS


def test_corta_al_llegar_al_maximo_de_rondas(camp, monkeypatch):
    monkeypatch.setattr(camp.C, "VERIFICAR_RONDAS", 1)
    camp._respondidos = {f"ChIJ{i:06d}" for i in range(0, 120, 2)}
    t = tanda(camp, monkeypatch, "2026-11-30", limite=25)
    assert len(camp._llamadas) == 1 and len(t["items"]) < 25


def test_se_queda_sin_candidatos(camp, monkeypatch):
    t = tanda(camp, monkeypatch, "2026-11-30", limite=500)
    assert len(t["items"]) == 119                                   # 120 menos una sucursal repetida


# --- seguridad del registro -----------------------------------------------
def test_registro_roto_corta(camp, monkeypatch):
    camp.REGISTRO.write_text("{ roto", encoding="utf-8")
    with pytest.raises(SystemExit):
        tanda(camp, monkeypatch, "2026-11-30")


def test_bajas_rotas_corta(camp, monkeypatch):
    camp.BAJAS.write_text("[ roto", encoding="utf-8")
    with pytest.raises(SystemExit):
        tanda(camp, monkeypatch, "2026-11-30")


def test_registro_con_formato_raro_corta(camp, monkeypatch):
    camp.REGISTRO.write_text("[]", encoding="utf-8")
    with pytest.raises(SystemExit):
        tanda(camp, monkeypatch, "2026-11-30")


def test_guarda_backup(camp, monkeypatch):
    tanda(camp, monkeypatch, "2026-11-30")
    assert list(camp.BACKUPS.glob("registro_*.json"))


# --- a quién se le escribe -------------------------------------------------
def test_respeta_bajas_y_su_dominio(camp, monkeypatch):
    camp.BAJAS.write_text(json.dumps(["info@negocio1.com", "local10@grupo-x.com", "negocio5@gmail.com"]))
    t = tanda(camp, monkeypatch, "2026-11-30", limite=500)
    mails = {i["email"] for i in t["items"]}
    assert "info@negocio1.com" not in mails and "negocio5@gmail.com" not in mails
    assert not any(m.endswith("@grupo-x.com") for m in mails)
    assert "negocio15@gmail.com" in mails                           # una baja de gmail no bloquea a todo gmail


def test_un_solo_negocio_por_dominio_de_empresa(camp, monkeypatch):
    t = tanda(camp, monkeypatch, "2026-11-30", limite=500)
    doms = [camp.dominio_empresa(i["email"]) for i in t["items"] if camp.dominio_empresa(i["email"])]
    assert len(doms) == len(set(doms))


def test_dominio_ya_contactado_otro_dia(camp, monkeypatch):
    camp.REGISTRO.write_text(json.dumps({"local10@grupo-x.com": registro_enviado("2026-11-02")}))
    t = tanda(camp, monkeypatch, "2026-11-30", limite=500)
    assert not any(i["email"].endswith("@grupo-x.com") for i in t["items"] if i["tipo"] == "primer mail")


def test_no_recontacta_a_nadie(camp, monkeypatch):
    t1 = tanda(camp, monkeypatch, "2026-11-30", limite=20)
    t2 = tanda(camp, monkeypatch, "2026-12-01", limite=20)
    primeros1 = {i["email"] for i in t1["items"]}
    primeros2 = {i["email"] for i in t2["items"] if i["tipo"] == "primer mail"}
    assert not primeros1 & primeros2


def test_mails_en_minuscula(camp, monkeypatch):
    t = tanda(camp, monkeypatch, "2026-11-30")
    assert all(i["email"] == i["email"].lower() for i in t["items"])


# --- días ------------------------------------------------------------------
@pytest.mark.parametrize("dia", ["2026-11-28", "2026-11-29", "2026-11-26", "2026-11-27",
                                 "2026-12-24", "2026-12-25", "2026-12-31", "2027-01-01"])
def test_no_arma_en_findes_ni_feriados(camp, monkeypatch, dia):
    with pytest.raises(SystemExit):
        tanda(camp, monkeypatch, dia)


def test_forzar_en_feriado(camp, monkeypatch):
    t = tanda(camp, monkeypatch, "2026-11-26", forzar=True)
    assert len(t["items"]) == 20


def test_feriados():
    import campana as c
    f = c.feriados_eeuu(2026)
    assert f[date(2026, 11, 26)] == "Thanksgiving" and f[date(2026, 11, 27)] == "Black Friday"
    assert date(2026, 7, 3) in f                                     # 4 de julio cae sábado: se toma el viernes
    assert date(2026, 9, 7) in f and date(2026, 5, 25) in f          # Labor Day y Memorial Day
    assert c.feriados_eeuu(2027)[date(2027, 11, 25)] == "Thanksgiving"


def test_dias_habiles_saltean_feriados():
    import campana as c
    assert c.dias_habiles(date(2026, 11, 20), date(2026, 11, 25)) == 3
    assert c.dias_habiles(date(2026, 11, 24), date(2026, 11, 30)) == 2  # 25 y 30 (26 y 27 son feriado)


# --- seguimientos ----------------------------------------------------------
def registro_enviado(dia, estado="enviado", **extra):
    r = {"negocio": "X", "rubro": RUBROS[0], "precio": 99, "ciudad": CIUDADES[0], "place_id": "ChIJx",
         "prioridad": "A", "asunto": "X's Google reviews", "estado": estado, "fechas": {"enviado": dia}}
    r["fechas"].update(extra)
    return r


def test_seguimiento_1_al_dia_habil_3(camp, monkeypatch):
    camp.REGISTRO.write_text(json.dumps({"a@a.com": registro_enviado("2026-11-30")}))
    for dia, esperado in (("2026-12-02", 0), ("2026-12-03", 1)):
        monkeypatch.setenv("RADAR_FECHA", dia)
        assert len(camp.seguimientos_pendientes(reg(camp))) == esperado


def test_seguimiento_2_espera_si_el_1_salio_tarde(camp, monkeypatch):
    camp.REGISTRO.write_text(json.dumps({
        "a@a.com": registro_enviado("2026-11-02", "seguimiento 1", **{"seguimiento 1": "2026-11-24"})}))
    monkeypatch.setenv("RADAR_FECHA", "2026-11-25")
    assert camp.seguimientos_pendientes(reg(camp)) == []
    monkeypatch.setenv("RADAR_FECHA", "2026-12-02")
    assert camp.seguimientos_pendientes(reg(camp)) == [("a@a.com", 2)]


def test_seguimiento_2_al_dia_habil_7_y_nunca_un_tercero(camp, monkeypatch):
    camp.REGISTRO.write_text(json.dumps({
        "a@a.com": registro_enviado("2026-11-16", "seguimiento 1", **{"seguimiento 1": "2026-11-19"}),
        "b@b.com": registro_enviado("2026-11-02", "seguimiento 2"),
    }))
    monkeypatch.setenv("RADAR_FECHA", "2026-11-24")
    assert camp.seguimientos_pendientes(reg(camp)) == []           # día hábil 6
    monkeypatch.setenv("RADAR_FECHA", "2026-11-25")
    assert camp.seguimientos_pendientes(reg(camp)) == [("a@a.com", 2)]


@pytest.mark.parametrize("estado", ["respondió", "baja", "rebotó", "descartado"])
def test_sin_seguimientos_si_respondio_o_baja(camp, monkeypatch, estado):
    camp.REGISTRO.write_text(json.dumps({"a@a.com": registro_enviado("2026-11-02", estado)}))
    monkeypatch.setenv("RADAR_FECHA", "2026-11-30")
    assert camp.seguimientos_pendientes(reg(camp)) == []


def test_seguimientos_que_no_entran_quedan_para_manana(camp, monkeypatch):
    camp.REGISTRO.write_text(json.dumps({f"s{i}@s{i}.com": registro_enviado("2026-11-16") for i in range(8)}))
    t = tanda(camp, monkeypatch, "2026-11-30", limite=5)
    assert len(t["items"]) == 5
    monkeypatch.setenv("RADAR_FECHA", "2026-12-01")
    r = reg(camp)
    camp.confirmar_armados(r)
    assert len(camp.seguimientos_pendientes(r)) == 3


# --- armado / enviado -------------------------------------------------------
def test_armado_no_cuenta_como_enviado_hasta_confirmar(camp, monkeypatch):
    tanda(camp, monkeypatch, "2026-11-30", limite=5)
    r = reg(camp)
    assert all(v["estado"] == "armado" and v["armado"]["fecha"] == "2026-11-30" for v in r.values())
    monkeypatch.setenv("RADAR_FECHA", "2026-12-01")
    camp.confirmar_armados(r)
    assert all(v["estado"] == "enviado" and v["fechas"]["enviado"] == "2026-11-30" and "armado" not in v
               for v in r.values())


def test_sin_confirmacion_automatica_espera_al_envio(camp, monkeypatch):
    monkeypatch.setattr(camp.C, "CONFIRMAR_AL_DIA_SIGUIENTE", False)
    t = tanda(camp, monkeypatch, "2026-11-30", limite=3)
    monkeypatch.setenv("RADAR_FECHA", "2026-12-02")
    r = reg(camp)
    camp.confirmar_armados(r)
    assert all(v["estado"] == "armado" for v in r.values())
    camp.cmd_marcar(t["items"][0]["email"], "enviado")
    assert reg(camp)[t["items"][0]["email"]]["fechas"]["enviado"] == "2026-12-02"


def test_dos_corridas_el_mismo_dia_no_pasan_el_tope(camp, monkeypatch):
    t1 = tanda(camp, monkeypatch, "2026-11-30", limite=20)
    with pytest.raises(SystemExit):
        tanda(camp, monkeypatch, "2026-11-30", limite=20)
    assert len(t1["items"]) == 20


def test_rebote_del_dia_libera_cupo(camp, monkeypatch):
    t1 = tanda(camp, monkeypatch, "2026-11-30", limite=20)
    camp.cmd_marcar(t1["items"][0]["email"], "rebotó")
    camp.cmd_marcar(t1["items"][1]["email"], "descartado")
    t2 = tanda(camp, monkeypatch, "2026-11-30", limite=20)
    assert len(t2["items"]) == 2
    assert (camp.TANDAS / "tanda_2026-11-30_completar.json").exists()


def test_descartar_seguimiento_lo_deja_para_otro_dia(camp, monkeypatch):
    camp.REGISTRO.write_text(json.dumps({"a@a.com": registro_enviado("2026-11-16")}))
    tanda(camp, monkeypatch, "2026-11-30", limite=1)
    camp.cmd_marcar("a@a.com", "descartado")
    r = reg(camp)
    assert r["a@a.com"]["estado"] == "enviado" and "armado" not in r["a@a.com"]
    monkeypatch.setenv("RADAR_FECHA", "2026-12-01")
    assert camp.seguimientos_pendientes(r) == [("a@a.com", 1)]


def test_baja_de_alguien_con_mail_armado(camp, monkeypatch, capsys):
    t = tanda(camp, monkeypatch, "2026-11-30", limite=2)
    e = t["items"][0]["email"]
    camp.cmd_marcar(e, "baja")
    assert "desprogramalo" in capsys.readouterr().out
    assert e in json.loads(camp.BAJAS.read_text())
    assert reg(camp)[e]["estado"] == "baja" and "armado" not in reg(camp)[e]


def test_baja_de_alguien_que_no_esta_en_el_registro(camp, monkeypatch):
    camp.cmd_marcar("Info@Desconocido.com ", "baja")
    assert "info@desconocido.com" in json.loads(camp.BAJAS.read_text())


def test_mail_invalido(camp):
    with pytest.raises(SystemExit):
        camp.cmd_marcar("esto no es un mail", "baja")


# --- horarios ---------------------------------------------------------------
def test_horarios_por_ciudad_escalonados_y_nunca_en_punto(camp, monkeypatch):
    t = tanda(camp, monkeypatch, "2026-11-30", limite=25)
    por_ciudad = {}
    for i in t["items"]:
        h, m = map(int, i["hora_art"].split(":"))
        assert m not in (0, 30)
        por_ciudad.setdefault(i["ciudad"], []).append(datetime.fromisoformat(i["envio_utc"]))
    rangos = {"Atlanta, GA": 12, "Houston, TX": 13, "Los Angeles, CA": 15}  # 10 locales en ART (invierno)
    for ciudad, horas in por_ciudad.items():
        primera = min(horas).astimezone(timezone(timedelta(hours=-3)))
        assert primera.hour == rangos[ciudad]
        horas.sort()
        assert all((b - a) >= timedelta(minutes=10) for a, b in zip(horas, horas[1:]))


def test_horario_de_verano():
    import campana as c
    it = [{"ciudad": "Atlanta, GA"}]
    c.asignar_horarios(it, date(2027, 6, 15))
    assert it[0]["hora_art"].startswith("11:")                     # en verano Atlanta está a 1 hora de Argentina


# --- formato de la tanda ----------------------------------------------------
def test_formato_de_la_tanda(camp, monkeypatch):
    t = tanda(camp, monkeypatch, "2026-11-30", limite=10)
    for i in t["items"]:
        assert i["tipo"] in camp.TIPOS_ENVIO
        assert i["precio"] in (59, 99)
        assert i["resenas"] and i["resenas"][0]["fecha"]
        assert i["negocio"] == "Negocio Numero " + i["negocio_original"].split()[2]
        assert i["hora_art"] and i["envio_utc"]


def test_prueba_no_guarda_nada(camp, monkeypatch):
    antes = camp.REGISTRO.read_text()
    tanda(camp, monkeypatch, "2026-11-30", prueba=True)
    assert camp.REGISTRO.read_text() == antes


def test_nombre_prolijo():
    import campana as c
    assert c.nombre_prolijo("NAIL TALK & SPA (GEORGIA TECH)") == "Nail Talk & Spa"
    assert c.nombre_prolijo("BZH Properties Inc.") == "BZH Properties"
    assert c.nombre_prolijo("4US MOVING") == "4US Moving"


def test_horario_sin_tzdata(monkeypatch):
    import campana as c
    monkeypatch.setattr(c, "ZoneInfo", None)                         # Windows sin el paquete tzdata
    it = [{"ciudad": "Houston, TX"}, {"ciudad": "Los Angeles, CA"}]
    c.asignar_horarios(it, date(2026, 12, 1))
    assert it[0]["hora_art"].startswith("13:") and it[1]["hora_art"].startswith("15:")
