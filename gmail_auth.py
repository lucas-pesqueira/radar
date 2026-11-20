"""Autoriza una sola vez el acceso a la casilla de envío (crear y mandar borradores, y leer la bandeja).

Uso (desde esta carpeta):
    py gmail_auth.py            abre el navegador para autorizar y guarda token_gmail.json
    py gmail_auth.py --probar   comprueba que el acceso funciona (cuenta los borradores)
    py gmail_auth.py --secretos muestra los 3 valores para cargar como secretos en GitHub

credentials.json y token_gmail.json son privados: están en .gitignore y no se comparten con nadie.
"""

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
CREDENCIALES = BASE / "credentials.json"
TOKEN = BASE / "token_gmail.json"
PERMISOS = ["https://www.googleapis.com/auth/gmail.compose",      # crear y mandar borradores
            "https://www.googleapis.com/auth/gmail.readonly"]     # leer respuestas, bajas y rebotes
CUENTA = "lucas@gettinkoprojects.com"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass


def autorizar():
    from google_auth_oauthlib.flow import InstalledAppFlow
    if not CREDENCIALES.exists():
        sys.exit(f"Falta {CREDENCIALES.name} en esta carpeta. Descargalo de Google Cloud (Clientes > tinko-script).")
    flujo = InstalledAppFlow.from_client_secrets_file(str(CREDENCIALES), PERMISOS)
    print(f"Se abre el navegador: entrá con {CUENTA} y aceptá el permiso.")
    cred = flujo.run_local_server(port=0, prompt="consent", access_type="offline", login_hint=CUENTA)
    if not cred.refresh_token:
        sys.exit("Google no devolvió el permiso permanente. Volvé a correr el comando.")
    TOKEN.write_text(cred.to_json(), encoding="utf-8")
    print(f"Listo: {TOKEN.name} guardado. No lo compartas ni lo subas a GitHub.")


def credenciales():
    from google.oauth2.credentials import Credentials
    if not TOKEN.exists():
        sys.exit("Todavía no autorizaste. Corré: py gmail_auth.py")
    return Credentials.from_authorized_user_file(str(TOKEN), PERMISOS)


def probar():
    from google.auth.transport.requests import AuthorizedSession
    s = AuthorizedSession(credenciales())
    r = s.get("https://gmail.googleapis.com/gmail/v1/users/me/drafts", params={"maxResults": 500})
    if r.status_code != 200:
        sys.exit(f"Gmail respondió {r.status_code}: {r.text[:300]}")
    print(f"Acceso OK. Borradores en la casilla: {len(r.json().get('drafts', []))}")
    r = s.get("https://gmail.googleapis.com/gmail/v1/users/me/messages", params={"q": "in:inbox", "maxResults": 5})
    if r.status_code != 200:
        sys.exit(f"No puedo leer la bandeja ({r.status_code}). Volvé a correr: py gmail_auth.py")
    print("Lectura de la bandeja OK.")


def secretos():
    t = json.loads(TOKEN.read_text(encoding="utf-8")) if TOKEN.exists() else sys.exit("Corré primero: py gmail_auth.py")
    print("Cargá estos 3 secretos en GitHub (repo radar-datos > Settings > Secrets and variables > Actions).")
    print("No los pegues en ningún chat.\n")
    print(f"GMAIL_CLIENT_ID\n{t['client_id']}\n")
    print(f"GMAIL_CLIENT_SECRET\n{t['client_secret']}\n")
    print(f"GMAIL_REFRESH_TOKEN\n{t['refresh_token']}")


if __name__ == "__main__":
    if "--probar" in sys.argv:
        probar()
    elif "--secretos" in sys.argv:
        secretos()
    else:
        autorizar()
