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
- `py campana.py tanda` anota a los prospectos como "armado" con su hora de envío. Claude deja los borradores en Gmail (sin programarlos) y `enviar.py` los manda a su hora desde GitHub Actions (repo `radar-datos`, cada 15 minutos en días hábiles). El borrador es la aprobación: si se borra, no sale. Lo que no salió en el día se libera al día siguiente (primer mail: vuelve a la lista; seguimiento: queda para otro día).
- `credentials.json` y `token_gmail.json` (acceso a Gmail) nunca se leen, imprimen ni suben. En GitHub van como secretos de `radar-datos`.
- No se arman tandas en fin de semana ni en feriados de EEUU (Thanksgiving, Black Friday, Navidad, etc.), salvo con `--forzar`.
- Un solo negocio por dominio de empresa en toda la campaña.
- Si `registro.json` o `bajas.json` están rotos, el script frena. Hay copias locales en `datos/backups/`.
- Los tests (`tests/`) usan datos inventados: este repo es público, nunca poner datos reales ahí.
- Los mails salen como borradores y se revisan antes de mandarse. Firma: Lucas Pesqueira / Tinko Projects, con dirección postal y línea de baja.

## Comandos
- `py campana.py estado` — resumen de la campaña
- `py campana.py tanda` — arma la tanda de hoy (verifica reseñas en vivo con Apify)
- `py campana.py respondio MAIL` — marca que respondió
- `py campana.py baja MAIL` — pidió no recibir más mails
- `py campana.py rebote MAIL` — el mail rebotó
- `py campana.py descartar MAIL` — un mail armado no se manda (primer mail: se descarta; seguimiento: queda para otro día)
- `py campana.py enviado MAIL` — el mail armado salió (lo usa el envío automático)
- `py enviar.py --prueba` — muestra qué mails saldrían ahora, sin mandar nada
- `py gmail_auth.py` — autoriza el acceso a Gmail (una sola vez); `--probar` lo comprueba
- `py -m pytest -q` — corre los tests (también corren solos en GitHub con cada push)
- Detalle de cada paso: ver `LEEME.md`

## Trabajo entre dos PC
Código (este repo): antes de empezar `git pull`; al terminar `git add .`, `git commit -m "..."`, `git push`. El registro y los prospectos (repo privado) los sincroniza `campana.py` solo.
