# Radar — prospección y campañas de Tinko Projects

Herramienta de Lucas para armar listas de negocios de EEUU (administradoras, mudanzas, restaurantes y uñas en Los Ángeles, Atlanta y Houston) y las tandas de mails de Tinko Projects (gestión de reseñas de Google).

## Cómo trabajar
- Español rioplatense, directo y sin relleno. No arrancar mensajes con "che".
- Cambiar solo lo que se pide. Mostrar el resultado antes de sugerir más cambios.
- Pasos numerados y comandos listos para copiar y pegar.

## Reglas que no se rompen
- Nunca leer, imprimir ni subir `token_apify*.txt`. No van a GitHub.
- Este repo es público. Nunca subir tokens, mails de prospectos ni los datos: `datos/`, `prospectos/`, `mails/` y `resultados/` están ignorados a propósito.
- `prospectos/` es otro repo, privado (`radar-datos`), anidado dentro de este. Ahí viven la lista de prospectos y el registro de la campaña (`prospectos/campana/`: `registro.json`, `bajas.json` y `tandas/`). `campana.py` hace `git pull` antes y `git push` después. Si avisa que no pudo sincronizar, no seguir hasta resolverlo.
- Las bajas se respetan siempre (CAN-SPAM). Quien pidió baja no recibe más mails.
- Antes de armar una tanda, revisar `ENVIOS_POR_DIA` en `config.py` (calentamiento: semana 1 unos 5 por día, semana 2 de 10 a 15, desde la semana 3 hasta 25).
- `py campana.py tanda` anota a los prospectos como enviados al armarse: correrlo solo el día del envío.
- Los mails salen como borradores y se revisan antes de mandarse. Firma: Lucas Pesqueira / Tinko Projects, con dirección postal y línea de baja.

## Comandos
- `py campana.py estado` — resumen de la campaña
- `py campana.py tanda` — arma la tanda de hoy (verifica reseñas en vivo con Apify)
- `py campana.py respondio MAIL` — marca que respondió
- `py campana.py baja MAIL` — pidió no recibir más mails
- Detalle de cada paso: ver `LEEME.md`

## Trabajo entre dos PC
Código (este repo): antes de empezar `git pull`; al terminar `git add .`, `git commit -m "..."`, `git push`. El registro y los prospectos (repo privado) los sincroniza `campana.py` solo.
