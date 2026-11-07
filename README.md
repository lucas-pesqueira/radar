# Radar

**English:** a Python toolkit that finds small U.S. businesses with unanswered Google reviews, builds a prioritized prospect list, and runs a small, careful outreach campaign (live review verification, follow-ups, unsubscribe registry). Built to sell a Google review management service.

Herramienta en Python que busca negocios chicos de EEUU con reseñas de Google sin responder, arma una lista de prospectos priorizada y lleva el registro de una campaña de mails: verificación de reseñas en vivo, seguimientos y bajas.

## Qué hace

| Script | Qué hace |
|---|---|
| `estudio.py` | Compara 12 rubros en 4 ciudades y mide dónde hay más negocios independientes con reseñas sin responder. |
| `prospectar.py` | Arma la lista de prospectos (administradoras, mudanzas, restaurantes y salones de uñas en Los Ángeles, Atlanta y Houston): busca el mail público de cada negocio, les da prioridad (A/B/C) y elige la reseña que conviene responder en el primer mail. |
| `campana.py` | Arma la tanda diaria, vuelve a verificar las reseñas en Google Maps antes de escribir, programa los seguimientos (días hábiles 3 y 7) y respeta las bajas. |
| `emails.py`, `analisis.py`, `apify.py` | Búsqueda de mails, métricas y cliente de la API de Apify. |

## Cómo se usa

1. `py -m pip install -r requirements.txt`
2. Poner la clave de Apify en `token_apify.txt` (o en la variable `APIFY_TOKEN`).
3. Pasos y costos de cada comando: ver [`LEEME.md`](LEEME.md).

## Decisiones de diseño

- **Gasto acotado:** cada comando estima el costo antes de correr y corta si no alcanza el crédito.
- **Retoma sin repetir:** lo descargado se guarda y no se vuelve a pagar.
- **Bajas primero:** quien pide no recibir más mails no vuelve a aparecer en ninguna tanda (CAN-SPAM).
- **Datos fuera del repo:** la lista de prospectos y el registro de la campaña viven en un repo privado aparte; las claves nunca se suben.

## Stack

Python 3 · `requests` · API de Apify (Google Maps).
