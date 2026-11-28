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
    monkeypatch.setattr(c, "INVALIDOS", datos / "campana" / "mails_invalidos.json")
    monkeypatch.setattr(c, "PROSPECTOS", datos / "prospectos_todos.csv")
    monkeypatch.setattr(c, "BACKUPS", tmp_path / "backups")
    monkeypatch.setattr(c, "lugares_guardados", lambda: {})
    monkeypatch.setattr(c, "indice_competencia", lambda: {})
    monkeypatch.setattr(c, "token", lambda: "x")
    monkeypatch.setattr(c, "tokens", lambda: ["x"])
    monkeypatch.setattr(c, "Apify", FakeApify)
    monkeypatch.setattr(c.C, "CONFIRMAR_AL_DIA_SIGUIENTE", True)
    c._respondidos = set()
    c._faltantes = set()
    c._llamadas = []

    def verificar(api, ids):
        c._llamadas.append(list(ids))
        return {pid: lugar(pid, respondida=pid in c._respondidos) for pid in ids if pid not in c._faltantes}
    monkeypatch.setattr(c, "verificar", verificar)
    c._invalidos = set()
    c._mails_verificados = []
    c._verificar_mails_real = c.verificar_mails

    def verificar_mails(api, emails):
        c._mails_verificados.append(list(emails))
        return {e: ("invalid" if e in c._invalidos else "valid") for e in emails}
    monkeypatch.setattr(c, "verificar_mails", verificar_mails)
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
    e = t["items"][0]["email"]
    camp.cmd_marcar(e, "enviado")                                    # lo marca el envío automático
    r = reg(camp)
    assert r[e]["estado"] == "enviado" and r[e]["fechas"]["enviado"] == "2026-11-30"
    assert sum(1 for v in r.values() if v["estado"] == "armado") == 2


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
    assert "borralo" in capsys.readouterr().out
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
        assert (11, 0) <= (h, m) <= (19, 41)                       # dentro de la ventana del envío automático
        por_ciudad.setdefault(i["ciudad"], []).append(datetime.fromisoformat(i["envio_utc"]))
    for ciudad, horas in por_ciudad.items():
        horas.sort()
        assert all((b - a) >= timedelta(minutes=10) for a, b in zip(horas, horas[1:])), (ciudad, [h.strftime("%H:%M") for h in horas][6:])


def local(it, zona):
    from zoneinfo import ZoneInfo
    return datetime.fromisoformat(it["envio_utc"]).astimezone(ZoneInfo(zona))


def test_horarios_por_rubro():
    import campana as c
    R = ["Restaurantes independientes", "Salones de uñas", "Mudanzas", "Administradoras de alquileres"]
    its = [{"ciudad": "Houston, TX", "rubro": R[i % 4]} for i in range(8)]
    c.asignar_horarios(its, date(2026, 12, 1))
    for it in its:
        h = local(it, "America/Chicago")
        franja = c.C.HORARIOS_RUBRO[c.rubro_clave(it["rubro"])][0]
        assert franja[0] <= h.strftime("%H:%M") <= franja[1], (it["rubro"], h)


def test_restaurantes_nunca_en_el_almuerzo():
    import campana as c
    its = [{"ciudad": "Atlanta, GA", "rubro": "Restaurantes independientes"} for _ in range(18)]
    c.asignar_horarios(its, date(2026, 12, 1))
    for it in its:
        hm = local(it, "America/New_York").strftime("%H:%M")
        assert not ("11:00" < hm < "14:30"), hm


def test_restaurantes_primero_si_la_manana_se_llena():
    """Si hay más mails que lugar a la mañana, los que pasan a la tarde no son los restaurantes."""
    import campana as c
    R = ["Mudanzas", "Administradoras de alquileres", "Restaurantes independientes"]
    its = [{"ciudad": "Atlanta, GA", "rubro": R[i % 3]} for i in range(15)]
    c.asignar_horarios(its, date(2026, 12, 1))
    for it in its:
        if it["rubro"] == "Restaurantes independientes":
            assert local(it, "America/New_York").hour < 11


def test_los_angeles_respeta_la_ventana():
    """A la tarde de Los Angeles ya no corre el envío (19:47 ART): nada se programa después de 19:40."""
    import campana as c
    its = [{"ciudad": "Los Angeles, CA", "rubro": "Mudanzas"} for _ in range(30)]
    c.asignar_horarios(its, date(2026, 12, 1))
    assert all(i["hora_art"] <= "19:41" and i["hora_art"] >= "11:00" for i in its)


def test_horario_de_verano():
    import campana as c
    it = [{"ciudad": "Atlanta, GA"}]
    c.asignar_horarios(it, date(2027, 6, 15))
    assert it[0]["hora_art"].startswith("11:")      # en verano Atlanta está a 1 hora: 9 locales = 10 ART, pero el envío arranca 11


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
    assert it[0]["hora_art"].startswith("12:") and it[1]["hora_art"].startswith("14:")   # 9 locales


# --- modo nube (--auto) -----------------------------------------------------
@pytest.mark.parametrize("dia", ["2026-11-28", "2026-11-26"])
def test_auto_en_feriado_termina_sin_error(camp, monkeypatch, dia):
    assert tanda(camp, monkeypatch, dia, auto=True) is None
    assert reg(camp) == {}


def test_auto_tanda_ya_armada_termina_sin_error(camp, monkeypatch):
    t = tanda(camp, monkeypatch, "2026-11-30", auto=True)
    assert len(t["items"]) == 20
    antes = reg(camp)
    assert tanda(camp, monkeypatch, "2026-11-30", auto=True) is None
    assert reg(camp) == antes
    with pytest.raises(SystemExit):                                  # a mano sigue avisando
        tanda(camp, monkeypatch, "2026-11-30")


def test_auto_push_fallido_termina_con_error(camp, monkeypatch):
    import subprocess
    (camp.DATOS / ".git").mkdir()
    def git_falso(*args):
        rc = 1 if args[0] in ("push",) else (1 if args[:2] == ("diff", "--cached") else 0)
        return subprocess.CompletedProcess(args, rc, stdout="origin" if args[0] == "remote" else "", stderr="rechazado")
    monkeypatch.setattr(camp, "_git", git_falso)
    with pytest.raises(SystemExit):
        camp.sync_despues("Tanda", estricto=True)
    camp.sync_despues("Tanda")                                        # sin estricto solo avisa


# --- varias cuentas de Apify ------------------------------------------------
class ApifyPorToken:
    """Cada token es una cuenta con su crédito libre (inventado)."""
    CREDITO = {}
    USADAS = []

    def __init__(self, tok):
        self.tok = tok

    def credito(self):
        libre = self.CREDITO.get(self.tok)
        return (None, None) if libre is None else (5 - libre, 5)


def test_usa_la_siguiente_cuenta_si_no_alcanza(camp, monkeypatch):
    ApifyPorToken.CREDITO = {"t0": 0.2, "t1": None, "t2": 3.0}
    monkeypatch.setattr(camp, "Apify", ApifyPorToken)
    monkeypatch.setattr(camp, "tokens", lambda: ["t0", "t1", "t2"])
    usadas = []
    original = camp.verificar
    monkeypatch.setattr(camp, "verificar", lambda api, ids: usadas.append(api.tok) or original(api, ids))
    t = tanda(camp, monkeypatch, "2026-11-30", limite=5)
    assert len(t["items"]) == 5 and set(usadas) == {"t2"}


def test_sin_credito_en_ninguna_cuenta_frena(camp, monkeypatch):
    ApifyPorToken.CREDITO = {"t0": 0.1, "t1": 0.2}
    monkeypatch.setattr(camp, "Apify", ApifyPorToken)
    monkeypatch.setattr(camp, "tokens", lambda: ["t0", "t1"])
    with pytest.raises(SystemExit, match="entre todas las cuentas"):
        tanda(camp, monkeypatch, "2026-11-30", limite=5)
    assert reg(camp) == {}


def test_cuentas_descuentan_lo_que_reservan(camp, monkeypatch):
    ApifyPorToken.CREDITO = {"a": 1.0, "b": 1.0}
    monkeypatch.setattr(camp, "Apify", ApifyPorToken)
    cu = camp.Cuentas(["a", "b"])
    assert cu.para(0.6)["n"] == 1 and cu.para(0.6)["n"] == 2 and cu.para(0.6) is None
    assert cu.libre_total() == 0.8


def test_orden_de_los_archivos_de_token(tmp_path, monkeypatch):
    import estudio
    for nombre, valor in [("token_apify10.txt", "j"), ("token_apify2.txt", "c"), ("token_apify.txt", "a"),
                          ("token_apify1.txt", "b"), ("token_apify3.txt", "")]:
        (tmp_path / nombre).write_text(valor + "\n", encoding="utf-8")
    monkeypatch.setattr(estudio, "BASE", tmp_path)
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    assert estudio.tokens() == ["a", "b", "c", "j"]
    monkeypatch.setenv("APIFY_TOKEN", "x1\ny2, x1")
    assert estudio.tokens() == ["x1", "y2"]


def test_tanda_saltea_mails_de_relleno(camp, monkeypatch):
    """Un mail de relleno que haya quedado en la lista (example@mail.com) nunca se arma."""
    import csv as _csv
    filas = list(_csv.DictReader(camp.PROSPECTOS.open(encoding="utf-8-sig")))
    filas[0]["email"] = "example@mail.com"
    with camp.PROSPECTOS.open("w", encoding="utf-8-sig", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=list(filas[0]))
        w.writeheader()
        w.writerows(filas)
    from emails import es_basura
    monkeypatch.setattr("emails.es_basura", lambda e: False)          # sin el filtro, entra
    antes = tanda(camp, monkeypatch, "2026-11-30", limite=20)
    assert "example@mail.com" in {i["email"] for i in antes["items"]}
    camp.REGISTRO.write_text("{}")
    monkeypatch.setattr("emails.es_basura", es_basura)                # con el filtro, no
    t = tanda(camp, monkeypatch, "2026-11-30", limite=20)
    assert "example@mail.com" not in {i["email"] for i in t["items"]} and len(t["items"]) == 20


# --- subida gradual del tope diario (22/11/2026) --------------------------------------------
def _reg(enviados, rebotados, dia):
    reg = {}
    for i in range(enviados):
        reg[f"a{i}@neg{i}-x.com"] = {"estado": "rebotó" if i < rebotados else "enviado",
                                     "fechas": {"enviado": dia}}
    return reg


@pytest.mark.parametrize("hoy_,enviados,rebotes,freno,esperado", [
    ("2026-11-23", 0, 0, False, 25),
    ("2026-12-06", 100, 0, False, 25),
    ("2026-12-07", 100, 2, False, 35),     # 2%: sube
    ("2026-12-07", 100, 3, False, 25),     # 3%: se queda abajo
    ("2026-12-07", 100, 0, True, 25),      # freno activo: se queda abajo
    ("2026-12-21", 100, 0, False, 50),
    ("2026-12-21", 100, 5, False, 35),
    ("2027-01-15", 0, 0, False, 50),
])
def test_tope_del_dia(hoy_, enviados, rebotes, freno, esperado):
    from datetime import date, timedelta
    import campana as K
    dia = date.fromisoformat(hoy_)
    reg = _reg(enviados, rebotes, (dia - timedelta(days=3)).isoformat())
    assert K.limite_del_dia(reg, dia, freno)[0] == esperado


def test_tope_no_cuenta_rebotes_viejos():
    from datetime import date
    import campana as K
    reg = _reg(10, 5, "2026-11-10")                       # rebotes de hace más de 14 días
    assert K.limite_del_dia(reg, date(2026, 12, 7))[0] == 35


# --- verificación de mails (27/11/2026) --------------------------------------
def test_mail_invalido_no_sale_y_se_reemplaza(camp, monkeypatch):
    """Un mail que no existe se saltea, otro ocupa su lugar y queda anotado para no volver a probarlo."""
    malos = {p["email"] for i, p in enumerate(prospectos()) if i % 2 == 0}
    camp._invalidos = set(malos)
    t = tanda(camp, monkeypatch, "2026-11-30", limite=10)
    mails = {i["email"] for i in t["items"]}
    assert len(t["items"]) == 10 and not (mails & malos)
    assert all(i["mail_verificado"] == "valid" for i in t["items"])
    anotados = set(camp.leer_invalidos())
    assert anotados and anotados <= malos
    assert not (anotados & set(reg(camp)))                    # no entran al registro
    assert any("no existe" in s["motivo"] for s in t["salteados"])


def test_invalidos_no_se_vuelven_a_verificar(camp, monkeypatch):
    camp._invalidos = {p["email"] for i, p in enumerate(prospectos()) if i % 2 == 0}
    tanda(camp, monkeypatch, "2026-11-30", limite=5)
    anotados = set(camp.leer_invalidos())
    assert anotados
    camp._mails_verificados.clear()
    tanda(camp, monkeypatch, "2026-12-01", limite=5)
    probados = {e for lote in camp._mails_verificados for e in lote}
    assert probados and not (anotados & probados)


def test_dudosos_salen_igual(camp, monkeypatch):
    """catch-all, unknown y risky no se descartan: solo 'invalid'."""
    estados = ["catch-all", "unknown", "risky"]
    monkeypatch.setattr(camp, "verificar_mails",
                        lambda api, emails: {e: estados[i % 3] for i, e in enumerate(emails)})
    t = tanda(camp, monkeypatch, "2026-11-30", limite=6)
    assert len(t["items"]) == 6 and camp.leer_invalidos() == {}


def test_si_falla_la_verificacion_de_mails_la_tanda_sigue(camp, monkeypatch):
    def falla(api, emails):
        raise camp.ErrorApify("caído")
    monkeypatch.setattr(camp, "verificar_mails", falla)
    t = tanda(camp, monkeypatch, "2026-11-30", limite=5)
    assert len(t["items"]) == 5


def test_prueba_no_verifica_mails(camp, monkeypatch):
    monkeypatch.setattr(camp, "lugares_guardados",
                        lambda: {f"ChIJ{i:06d}": (lugar(f"ChIJ{i:06d}"), datetime.now(timezone.utc))
                                 for i in range(120)})
    tanda(camp, monkeypatch, "2026-11-30", limite=5, prueba=True)
    assert camp._mails_verificados == []


def test_se_puede_apagar(camp, monkeypatch):
    monkeypatch.setattr(camp.C, "VERIFICAR_MAILS", False)
    camp._invalidos = {"info@negocio1.com"}
    tanda(camp, monkeypatch, "2026-11-30", limite=5)
    assert camp._mails_verificados == []


def test_verificar_mails_lee_la_salida_del_actor(camp):
    class Api:
        def arrancar(self, actor, entrada, tope):
            assert actor == camp.C.ACTOR_MAILS and tope >= 0.5
            self.entrada = entrada
            return {"id": "r1"}

        def esperar(self, rid, al_avanzar=None, cada=15):
            return {"defaultDatasetId": "d1"}

        def items(self, did):
            return [{"email": "A@x.com", "status": "invalid"}, {"email": "b@y.com", "status": "valid"}]
    out = camp._verificar_mails_real(Api(), ["a@x.com", "b@y.com", "c@z.com"])
    assert out == {"a@x.com": "invalid", "b@y.com": "valid", "c@z.com": "unknown"}


# --- seguimiento 3 (27/11/2026) ----------------------------------------------
def test_seguimiento_3_al_dia_habil_12(camp, monkeypatch):
    camp.REGISTRO.write_text(json.dumps({
        "a@a.com": registro_enviado("2026-11-30", "seguimiento 2",
                                    **{"seguimiento 1": "2026-12-03", "seguimiento 2": "2026-12-09"})}))
    monkeypatch.setenv("RADAR_FECHA", "2026-12-15")                 # día hábil 11
    assert camp.seguimientos_pendientes(reg(camp)) == []
    monkeypatch.setenv("RADAR_FECHA", "2026-12-16")                 # día hábil 12
    assert camp.seguimientos_pendientes(reg(camp)) == [("a@a.com", 3)]


def test_seguimiento_3_espera_si_el_2_salio_tarde(camp, monkeypatch):
    camp.REGISTRO.write_text(json.dumps({
        "a@a.com": registro_enviado("2026-11-30", "seguimiento 2",
                                    **{"seguimiento 1": "2026-12-03", "seguimiento 2": "2026-12-15"})}))
    monkeypatch.setenv("RADAR_FECHA", "2026-12-16")
    assert camp.seguimientos_pendientes(reg(camp)) == []
    monkeypatch.setenv("RADAR_FECHA", "2026-12-22")                 # 5 días hábiles después del 2
    assert camp.seguimientos_pendientes(reg(camp)) == [("a@a.com", 3)]


def test_sin_seguimiento_3_para_el_seguimiento_2_viejo(camp, monkeypatch):
    """Antes del 30/11/2026 el seguimiento 2 prometía que era el último: a esos no se les escribe más."""
    camp.REGISTRO.write_text(json.dumps({
        "a@a.com": registro_enviado("2026-11-10", "seguimiento 2",
                                    **{"seguimiento 1": "2026-11-13", "seguimiento 2": "2026-11-25"})}))
    monkeypatch.setenv("RADAR_FECHA", "2027-01-15")
    assert camp.seguimientos_pendientes(reg(camp)) == []


def test_nunca_un_cuarto_seguimiento(camp, monkeypatch):
    camp.REGISTRO.write_text(json.dumps({
        "a@a.com": registro_enviado("2026-11-30", "seguimiento 3",
                                    **{"seguimiento 1": "2026-12-03", "seguimiento 2": "2026-12-09",
                                       "seguimiento 3": "2026-12-16"})}))
    monkeypatch.setenv("RADAR_FECHA", "2027-01-15")
    assert camp.seguimientos_pendientes(reg(camp)) == []


def test_seguimiento_3_entra_en_la_tanda(camp, monkeypatch):
    camp.REGISTRO.write_text(json.dumps({
        "a@a.com": registro_enviado("2026-11-30", "seguimiento 2",
                                    **{"seguimiento 1": "2026-12-03", "seguimiento 2": "2026-12-09"})}))
    t = tanda(camp, monkeypatch, "2026-12-16", limite=3)
    assert t["items"][0]["tipo"] == "seguimiento 3" and t["items"][0]["email"] == "a@a.com"
    assert reg(camp)["a@a.com"]["armado"]["tipo"] == "seguimiento 3"


# --- comparación con la competencia (27/11/2026) -----------------------------
def vecino(pid, lat, nombre, responde, cat="Italian restaurant", n=5, busqueda="restaurant"):
    rv = [{"reviewOrigin": "Google", "responseFromOwnerText": "Thanks!" if responde else ""} for _ in range(n)]
    return {"placeId": pid, "title": nombre, "categoryName": cat, "searchString": busqueda,
            "location": {"lat": lat, "lng": -84.0}, "reviews": rv}


def indice(lista):
    return {l["placeId"]: lista for l in lista}


def test_competencia_cuenta_los_5_mas_cercanos(camp):
    lista = [vecino("yo", 33.0, "Mi Lugar", False),
             vecino("v1", 33.001, "Uno Grill", True), vecino("v2", 33.002, "Dos Bistro", False),
             vecino("v3", 33.003, "Tres Cafe", True), vecino("v4", 33.004, "Cuatro", True),
             vecino("v5", 33.005, "Cinco", False),
             vecino("lejos", 33.5, "Lejos Grill", True)]                  # sexto más cercano: no cuenta
    assert camp.competencia("yo", indice(lista)) == {"comp_responden": 3, "comp_de": 5, "comp_ejemplo": "Uno Grill"}


def test_competencia_vacia_si_pocos_responden_o_faltan_datos(camp):
    lista = [vecino("yo", 33.0, "Mi Lugar", False)] + [
        vecino(f"v{i}", 33.0 + i / 1000, f"Vecino {i}", i == 1) for i in range(1, 6)]
    assert camp.competencia("yo", indice(lista)) == {}                  # solo 1 de 5
    assert camp.competencia("otro", indice(lista)) == {}                # sin datos del negocio
    assert camp.competencia("yo", indice(lista[:4])) == {}              # menos de 5 vecinos con datos


def test_competencia_ignora_otro_rubro_cadenas_sucursales_y_pocas_resenas(camp):
    lista = [vecino("yo", 33.0, "Mi Lugar", False),
             vecino("bar", 33.0001, "Bar Cualquiera", True, cat="Bar"),
             vecino("cad", 33.0002, "Olive Garden Italian Kitchen", True),
             vecino("suc", 33.0003, "Mi Lugar", True),
             vecino("poc", 33.0004, "Poquitas", True, n=2),
             vecino("v1", 33.001, "Uno Grill", True), vecino("v2", 33.002, "Dos Bistro", True),
             vecino("v3", 33.003, "Tres", False), vecino("v4", 33.004, "Cuatro", False),
             vecino("v5", 33.005, "Cinco", False)]
    assert camp.competencia("yo", indice(lista)) == {"comp_responden": 2, "comp_de": 5, "comp_ejemplo": "Uno Grill"}


def test_nombre_ejemplo_presentable(camp):
    assert camp.nombre_ejemplo("Polished Nail Bar- Downtown LA") == "Polished Nail Bar"
    assert camp.nombre_ejemplo("TRES CAFE LLC") == "Tres Cafe"
    assert camp.nombre_ejemplo("m") == ""


def test_la_tanda_suma_la_competencia(camp, monkeypatch):
    monkeypatch.setattr(camp, "competencia", lambda pid, idx: {"comp_responden": 3, "comp_de": 5,
                                                              "comp_ejemplo": "Uno Grill"})
    t = tanda(camp, monkeypatch, "2026-11-30", limite=3)
    assert all(i["comp_ejemplo"] == "Uno Grill" for i in t["items"])
