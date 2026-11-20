"""Envío automático: manda a su hora los borradores de la tanda del día.

Uso (desde esta carpeta):
    py enviar.py             manda los mails cuya hora ya llegó (en GitHub corre solo cada 15 minutos)
    py enviar.py --prueba    muestra qué mandaría ahora, sin mandar nada
    py enviar.py --probar    comprueba el acceso a Gmail (cuenta los borradores)

Cómo decide:
- Solo manda mails que están "armados" para hoy en el registro y cuya hora (envio_utc) ya llegó.
- Busca en Gmail el borrador dirigido a ese mail. Si no hay borrador, no manda nada:
  el borrador es la aprobación de Lucas. Si lo borrás, no sale.
- Nunca manda a una baja, a un dominio bloqueado ni a quien ya respondió.
- Al mandar, Gmail borra el borrador: así un mail no puede salir dos veces.
- Después de mandar, marca el mail como enviado en el registro y lo sube a GitHub.

Credenciales: en GitHub, los secretos GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET y GMAIL_REFRESH_TOKEN.
En la PC, token_gmail.json (lo crea gmail_auth.py).
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from email.utils import getaddresses

import requests

import campana as K
from estudio import BASE

GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
TOKEN_LOCAL = BASE / "token_gmail.json"
AVISO = timedelta(minutes=20)       # un mail sin borrador se reporta como error solo en la primera corrida

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass


class ErrorGmail(Exception):
    pass


# ---------------------------------------------------------------------------
# Gmail
# ---------------------------------------------------------------------------
def credenciales():
    """(client_id, client_secret, refresh_token) desde los secretos de GitHub o token_gmail.json."""
    env = [os.environ.get(k, "").strip() for k in ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN")]
    if all(env):
        return tuple(env)
    if TOKEN_LOCAL.exists():
        t = json.loads(TOKEN_LOCAL.read_text(encoding="utf-8"))
        return t["client_id"], t["client_secret"], t["refresh_token"]
    sys.exit("No hay credenciales de Gmail. En la PC corré: py gmail_auth.py")


class Gmail:
    def __init__(self, sesion=None):
        self.s = sesion or requests.Session()
        cid, secreto, refresh = credenciales()
        r = self.s.post("https://oauth2.googleapis.com/token", timeout=30, data={
            "client_id": cid, "client_secret": secreto, "refresh_token": refresh, "grant_type": "refresh_token"})
        if r.status_code != 200:
            raise ErrorGmail(f"No se pudo renovar el acceso a Gmail ({r.status_code}): {r.text[:300]}")
        self.s.headers["Authorization"] = "Bearer " + r.json()["access_token"]

    def _pedir(self, metodo, ruta, **kw):
        for intento in range(4):
            r = self.s.request(metodo, GMAIL + ruta, timeout=60, **kw)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(4 * (intento + 1))
                continue
            if r.status_code >= 400:
                raise ErrorGmail(f"Gmail respondió {r.status_code} en {ruta}: {r.text[:300]}")
            return r.json()
        raise ErrorGmail(f"Gmail no respondió bien en {ruta} después de varios intentos.")

    def borradores(self):
        """{mail destinatario: [(id del borrador, asunto)]} de todos los borradores."""
        ids, token = [], None
        while True:
            params = {"maxResults": 500}
            if token:
                params["pageToken"] = token
            r = self._pedir("GET", "/drafts", params=params)
            ids += [d["id"] for d in r.get("drafts", [])]
            token = r.get("nextPageToken")
            if not token:
                break
        out = {}
        for did in ids:
            d = self._pedir("GET", f"/drafts/{did}", params={"format": "metadata",
                                                            "metadataHeaders": ["To", "Subject"]})
            cab = {h["name"].lower(): h["value"] for h in d.get("message", {}).get("payload", {}).get("headers", [])}
            for _, mail in getaddresses([cab.get("to", "")]):
                if mail:
                    out.setdefault(mail.strip().lower(), []).append((did, cab.get("subject", "")))
        return out

    def mandar(self, draft_id):
        return self._pedir("POST", "/drafts/send", json={"id": draft_id})


# ---------------------------------------------------------------------------
# Qué mandar
# ---------------------------------------------------------------------------
def a_mandar(registro, bajas, ahora, dia):
    """Mails armados para hoy cuya hora ya llegó, en orden de horario."""
    doms = K.dominios_bloqueados(bajas)
    out = []
    for email, r in registro.items():
        a = r.get("armado")
        if not a or a["fecha"] != dia:
            continue
        if K.esta_bloqueado(email, bajas, doms) or r.get("estado") in ("respondió", "baja", "rebotó", "descartado"):
            continue
        cuando = datetime.fromisoformat(a["envio_utc"])
        if cuando <= ahora:
            out.append((cuando, email))
    return sorted(out)


def elegir_borrador(email, asunto, borradores):
    """El borrador dirigido a ese mail. Si hay varios, el del asunto de la campaña; si sigue habiendo
    más de uno, ninguno (mejor no mandar que mandar el equivocado)."""
    cands = borradores.get(email, [])
    if len(cands) > 1:
        norm = lambda s: re.sub(r"^\s*(re|fwd?):\s*", "", s or "", flags=re.I).strip().lower()
        cands = [c for c in cands if norm(c[1]) == norm(asunto)]
    return cands[0][0] if len(cands) == 1 else None, len(borradores.get(email, []))


def enviar(prueba=False, ahora=None, gmail=None):
    ahora = ahora or datetime.now(timezone.utc)
    dia = K.hoy().isoformat()
    registro = K.leer_registro()
    bajas = K.leer_bajas()
    pendientes = a_mandar(registro, bajas, ahora, dia)
    if not pendientes:
        print(f"{ahora:%H:%M} UTC: nada para mandar ahora.")
        return [], []
    gmail = gmail or Gmail()
    borradores = gmail.borradores()
    enviados, problemas = [], []
    for cuando, email in pendientes:
        r = registro[email]
        tipo = r["armado"]["tipo"]
        draft, cuantos = elegir_borrador(email, r.get("asunto", ""), borradores)
        if not draft:
            motivo = "no hay borrador (no aprobado o ya mandado a mano)" if not cuantos else \
                f"hay {cuantos} borradores para ese mail y no sé cuál es"
            print(f"  NO SALE  {tipo:<14} {email}: {motivo}")
            if ahora - cuando < AVISO:                              # se avisa una sola vez, no cada 15 minutos
                problemas.append((email, motivo))
            continue
        if prueba:
            print(f"  saldría  {tipo:<14} {email} ({r['negocio']})")
            continue
        gmail.mandar(draft)
        K.aplicar_envio(r, dia)
        enviados.append(email)
        print(f"  ENVIADO  {tipo:<14} {email} ({r['negocio']})")
        K.guardar_seguro(K.REGISTRO, registro)                   # se guarda después de cada envío
    return enviados, problemas


def subir(enviados, dia):
    """Sube el registro. Si mientras tanto la PC subió otro cambio, se toma el registro nuevo
    y se vuelven a marcar los enviados (así no se pisa nada)."""
    if not K._usa_git():
        return
    for intento in range(3):
        K._git("add", "-A")
        if K._git("diff", "--cached", "--quiet").returncode != 0:
            K._git("commit", "-m", f"Enviados {len(enviados)} mails ({dia})")
        if K._git("push").returncode == 0:
            print("Registro subido a GitHub.")
            return
        K._git("fetch")
        K._git("reset", "--hard", "@{u}")
        registro = K.leer_registro()
        for e in enviados:
            r = registro.get(e)
            if r and (r.get("armado") or {}).get("fecha") == dia:
                K.aplicar_envio(r, dia)
        K.guardar_json(K.REGISTRO, registro)
    sys.exit("No se pudo subir el registro a GitHub después de 3 intentos. Los mails SÍ salieron.")


def main():
    prueba = "--prueba" in sys.argv
    try:
        if "--probar" in sys.argv:
            b = Gmail().borradores()
            print(f"Acceso a Gmail OK. Borradores: {sum(len(v) for v in b.values())}")
            return
        if not prueba:
            K.sync_antes()
        enviados, problemas = enviar(prueba=prueba)
        if enviados:
            subir(enviados, K.hoy().isoformat())
        if problemas and not prueba:
            # Termina con error para que GitHub avise por mail.
            sys.exit(f"{len(problemas)} mails no salieron. Revisá los borradores.")
    except ErrorGmail as e:
        sys.exit(f"Error de Gmail: {e}")


if __name__ == "__main__":
    main()
