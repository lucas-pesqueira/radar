"""Envío automático: manda a su hora los borradores de la tanda del día.

Uso (desde esta carpeta):
    py enviar.py             manda los mails cuya hora ya llegó (en GitHub corre solo cada 15 minutos)
    py enviar.py --prueba    muestra qué mandaría ahora, sin mandar nada
    py enviar.py --probar    comprueba el acceso a Gmail (cuenta los borradores)

Antes de mandar lee la bandeja (bandeja.py) y marca solo respuestas, bajas y rebotes: a quien
respondió, pidió la baja o rebotó no le sale nada más, aunque tenga el borrador listo.

Antes de mandar cada borrador lo revisa con reglas fijas (control.py): firma, dirección y línea de
baja, precio, sin links, nombre del negocio y asunto. Si algo no cuadra, no sale y avisa.
Con el freno de emergencia activo (muchos rebotes o bajas), no salen primeros mails, solo seguimientos.

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

import bandeja as B
import campana as K
import control as X
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

    def borrador(self, draft_id):
        """Texto del borrador (versión de texto plano)."""
        d = self._pedir("GET", f"/drafts/{draft_id}", params={"format": "full"})
        return B.texto_de(d.get("message", {}).get("payload"), preferir_plano=True)

    def ids_bandeja(self, consulta):
        """Ids de los mails de la bandeja que cumplen la búsqueda (más viejos primero)."""
        ids, token = [], None
        while True:
            params = {"q": consulta, "maxResults": 500}
            if token:
                params["pageToken"] = token
            r = self._pedir("GET", "/messages", params=params)
            ids += [m["id"] for m in r.get("messages", [])]
            token = r.get("nextPageToken")
            if not token:
                break
        return ids[::-1]

    def mensaje(self, mid):
        return self._pedir("GET", f"/messages/{mid}", params={"format": "full"})


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
    asuntos = {did: asunto for lista in borradores.values() for did, asunto in lista}
    frenado = X.freno_activo()
    enviados, problemas = [], []
    for cuando, email in pendientes:
        r = registro[email]
        tipo = r["armado"]["tipo"]
        avisar = ahora - cuando < AVISO                             # se avisa una sola vez, no cada 15 minutos
        if frenado and tipo == "primer mail":
            print(f"  FRENADO  {tipo:<14} {email}: freno de emergencia activo")
            continue
        draft, cuantos = elegir_borrador(email, r.get("asunto", ""), borradores)
        motivo = None
        if not draft:
            motivo = "no hay borrador (no aprobado o ya mandado a mano)" if not cuantos else \
                f"hay {cuantos} borradores para ese mail y no sé cuál es"
        else:
            fallas = X.revisar_borrador(gmail.borrador(draft), asuntos.get(draft, ""), r, tipo)
            if fallas:
                motivo = "el borrador no pasó el control: " + "; ".join(fallas)
        if motivo:
            print(f"  NO SALE  {tipo:<14} {email}: {motivo}")
            if avisar:
                problemas.append((email, motivo))
                if not prueba:
                    X.anotar(dia, "no_salieron", {"email": email, "tipo": tipo, "motivo": motivo}, "email")
            continue
        if prueba:
            print(f"  saldría  {tipo:<14} {email} ({r['negocio']})")
            continue
        gmail.mandar(draft)
        K.aplicar_envio(r, dia)
        enviados.append(email)
        print(f"  ENVIADO  {tipo:<14} {email} ({r['negocio']})")
        K.guardar_seguro(K.REGISTRO, registro)                   # se guarda después de cada envío
        X.anotar(dia, "enviados", {"email": email, "tipo": tipo, "hora_utc": ahora.isoformat(timespec="minutes")},
                 "email")
    return enviados, problemas


def revisar_bandeja(gmail, dia):
    """Marca respuestas, bajas y rebotes antes de mandar. Si falta el permiso de lectura,
    avisa y sigue (no frena los envíos). Devuelve (marcas, ids revisados)."""
    registro = K.leer_registro()
    bajas = K.leer_estricto(K.BAJAS, [], list)
    try:
        marcas, vistos = B.revisar(gmail, registro, bajas, dia)
    except ErrorGmail as e:
        if " 403 " in f" {e} ":
            print("AVISO: falta el permiso para leer la bandeja. En la PC: py gmail_auth.py "
                  "y actualizá el secreto GMAIL_REFRESH_TOKEN. Los envíos siguen igual.")
            return [], []
        raise
    if marcas:
        K.guardar_seguro(K.BAJAS, bajas)
        K.guardar_seguro(K.REGISTRO, registro)
        for e, estado, remitente, resumen in marcas:
            X.anotar(dia, "marcados", {"email": e, "estado": estado, "de": remitente, "texto": resumen[:120]})
    if vistos:
        B.guardar_vistos(B.leer_vistos() + vistos)
    return marcas, vistos


def rehacer(enviados, marcas, vistos, dia):
    """Vuelve a aplicar lo de esta corrida sobre el registro recién bajado de GitHub."""
    registro = K.leer_registro()
    bajas = K.leer_estricto(K.BAJAS, [], list)
    for e, estado, remitente, _ in marcas:
        B.marcar(registro, bajas, e, estado, dia, [remitente] if estado == "baja" and remitente != e else [])
    for e in enviados:
        r = registro.get(e)
        if r and (r.get("armado") or {}).get("fecha") == dia:
            K.aplicar_envio(r, dia)
    K.guardar_json(K.REGISTRO, registro)
    K.guardar_json(K.BAJAS, bajas)
    for e, estado, remitente, resumen in marcas:
        X.anotar(dia, "marcados", {"email": e, "estado": estado, "de": remitente, "texto": resumen[:120]})
    for e in enviados:
        X.anotar(dia, "enviados", {"email": e, "tipo": (registro.get(e) or {}).get("estado", "")}, "email")
    X.activar_freno(registro, dia)
    X.actualizar(registro, bajas, dia)
    if vistos:
        B.guardar_vistos(B.leer_vistos() + [v for v in vistos if v not in set(B.leer_vistos())])


def subir(enviados, dia, marcas=(), vistos=()):
    """Sube el registro. Si mientras tanto la PC subió otro cambio, se toma el registro nuevo
    y se vuelve a aplicar lo de esta corrida (así no se pisa nada)."""
    if not K._usa_git():
        return
    partes = [f"{len(enviados)} enviados"] if enviados else []
    partes += [f"{len(marcas)} marcados por la bandeja"] if marcas else []
    mensaje = f"Envío automático: {', '.join(partes) or 'bandeja revisada'} ({dia})"
    for intento in range(3):
        K._git("add", "-A")
        if K._git("diff", "--cached", "--quiet").returncode == 0:
            return
        K._git("commit", "-m", mensaje)
        if K._git("push").returncode == 0:
            print("Registro subido a GitHub.")
            return
        K._git("fetch")
        K._git("reset", "--hard", "@{u}")
        rehacer(enviados, marcas, vistos, dia)
    sys.exit("No se pudo subir el registro a GitHub después de 3 intentos. Los mails SÍ salieron.")


def main():
    prueba = "--prueba" in sys.argv
    try:
        if "--probar" in sys.argv:
            g = Gmail()
            b = g.borradores()
            print(f"Acceso a Gmail OK. Borradores: {sum(len(v) for v in b.values())}")
            try:
                print(f"Lectura de la bandeja OK. Mails de los últimos 4 días: {len(g.ids_bandeja(B.BUSQUEDA))}")
            except ErrorGmail as e:
                print(f"Lectura de la bandeja: SIN PERMISO todavía ({str(e)[:80]}). Corré py gmail_auth.py")
            return
        dia = K.hoy().isoformat()
        marcas, vistos = [], []
        gmail = None
        if not prueba:
            K.sync_antes()
            gmail = Gmail()
            marcas, vistos = revisar_bandeja(gmail, dia)
        frenado_ahora = None
        if not prueba:
            frenado_ahora = X.activar_freno(K.leer_registro(), dia)
            if frenado_ahora:
                print(f"FRENO DE EMERGENCIA: {frenado_ahora}. No salen primeros mails hasta destrabarlo.")
        enviados, problemas = enviar(prueba=prueba, gmail=gmail)
        if frenado_ahora:
            problemas.append(("FRENO", frenado_ahora))
        if not prueba:
            m = X.actualizar(K.leer_registro(), K.leer_bajas(), dia)
            for a in m["alertas"]:
                print(f"ALERTA: {a}")
        if enviados or marcas or vistos or frenado_ahora or problemas:
            subir(enviados, dia, marcas, vistos)
        if problemas and not prueba:
            # Termina con error para que GitHub avise por mail.
            detalle = "\n".join(f"  {e}: {m}" for e, m in problemas)
            sys.exit(f"{len(problemas)} avisos:\n{detalle}")
    except ErrorGmail as e:
        sys.exit(f"Error de Gmail: {e}")


if __name__ == "__main__":
    main()
