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
- Todo corre solo en la nube, en días hábiles: a las 6:47 ART la Action `tanda` de `radar-datos` corre `campana.py tanda --auto` (anota a los prospectos como "armado" con su hora de envío); a las 8:42 ART una tarea programada de Claude escribe los borradores en Gmail según `prospectos/campana/plantillas.md` (sin programarlos); y la Action `envio` (`enviar.py`, cada 15 minutos) primero lee la bandeja (`bandeja.py`: marca solo respuestas, bajas y rebotes) y después manda los borradores a su hora. `py campana.py tanda` a mano sigue funcionando igual. El borrador es la aprobación: si se borra, no sale. Lo que no salió en el día se libera al día siguiente (primer mail: vuelve a la lista; seguimiento: queda para otro día).
- Horarios: las Actions `tanda` y `envio` las dispara cron-job.org (tareas "Tinko - tanda" y "Tinko - envio", creadas con `py cronjobs.py`) por la API de GitHub. El cron propio de GitHub no es confiable (puede atrasarse horas): en `envio` queda solo de respaldo y en `tanda` no está.
- Controles (`control.py`): antes de mandar, cada borrador se revisa con reglas fijas (firma, dirección y línea de baja, precio, sin links, nombre del negocio, asunto); si falla, no sale. Freno de emergencia: más de 2 rebotes en los últimos 30 primeros mails o más de 2 bajas en un día frenan los primeros mails (los seguimientos siguen) hasta `py campana.py destrabar`. Métricas, alertas y registro diario quedan en `prospectos/campana/metricas.json` y `diario.json`.
- `estudio.py` es la herramienta del estudio de nichos inicial (ya cumplida): no se usa en el día a día.
- `credentials.json` y `token_gmail.json` (acceso a Gmail) nunca se leen, imprimen ni suben. En GitHub van como secretos de `radar-datos`.
- No se arman tandas en fin de semana ni en feriados de EEUU (Thanksgiving, Black Friday, Navidad, etc.), salvo con `--forzar`.
- Un solo negocio por dominio de empresa en toda la campaña.
- Si `registro.json` o `bajas.json` están rotos, el script frena. Hay copias locales en `datos/backups/`.
- Los tests (`tests/`) usan datos inventados: este repo es público, nunca poner datos reales ahí.
- Los mails salen como borradores y se revisan antes de mandarse. Firma: Lucas Pesqueira / Tinko Projects, con dirección postal y línea de baja.

## Comandos
- `py campana.py estado` — resumen de la campaña (con alertas)
- `py campana.py destrabar` — destraba el freno de emergencia, después de revisar los rebotes o bajas
- `py campana.py tanda` — arma la tanda de hoy (verifica reseñas en vivo con Apify)
- `respondio` / `baja` / `rebote` los marca solo el envío automático al leer la bandeja; a mano sirven para corregir
- `py campana.py respondio MAIL` — marca que respondió
- `py campana.py baja MAIL` — pidió no recibir más mails
- `py campana.py rebote MAIL` — el mail rebotó
- `py campana.py descartar MAIL` — un mail armado no se manda (primer mail: se descarta; seguimiento: queda para otro día)
- `py campana.py enviado MAIL` — el mail armado salió (lo usa el envío automático)
- `py enviar.py --prueba` — muestra qué mails saldrían ahora, sin mandar nada
- `py gmail_auth.py` — autoriza el acceso a Gmail (crear y mandar borradores, y leer la bandeja); `--probar` lo comprueba
- `py -m pytest -q` — corre los tests (también corren solos en GitHub con cada push)
- Detalle de cada paso: ver `LEEME.md`

## Trabajo entre dos PC
Código (este repo): antes de empezar `git pull`; al terminar `git add .`, `git commit -m "..."`, `git push`. El registro y los prospectos (repo privado) los sincroniza `campana.py` solo.
