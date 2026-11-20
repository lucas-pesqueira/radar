"""Tests de cronjobs.py (sin llamar a ninguna API)."""
import json

import cronjobs as CJ


def test_tareas_bien_armadas():
    t = CJ.armar_tarea("Tinko - envio", CJ.TAREAS["Tinko - envio"], "clave-falsa")
    assert t["requestMethod"] == 1 and t["enabled"]
    assert t["url"].endswith("/radar-datos/actions/workflows/envio.yml/dispatches")
    assert t["schedule"]["timezone"] == "America/Argentina/Buenos_Aires"
    assert t["schedule"]["wdays"] == [1, 2, 3, 4, 5]
    assert t["schedule"]["hours"] == list(range(11, 20)) and 0 not in t["schedule"]["minutes"]
    assert t["extendedData"]["headers"]["Authorization"] == "Bearer clave-falsa"
    assert json.loads(t["extendedData"]["body"]) == {"ref": "main"}


def test_tanda_a_las_6_47():
    t = CJ.armar_tarea("Tinko - tanda", CJ.TAREAS["Tinko - tanda"], "x")
    assert t["url"].endswith("/tanda.yml/dispatches")
    assert (t["schedule"]["hours"], t["schedule"]["minutes"]) == ([6], [47])


def test_prospeccion_los_domingos():
    t = CJ.armar_tarea("Tinko - prospeccion", CJ.TAREAS["Tinko - prospeccion"], "x")
    assert t["url"].endswith("/prospeccion.yml/dispatches") and t["schedule"]["wdays"] == [0]
