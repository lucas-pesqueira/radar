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
- Prospección (`prospectar.py`): los datos viven en `prospectos/prospeccion/` (repo privado, crudos comprimidos `.json.gz`). La Action `prospeccion` (domingos 10:07 ART por cron-job.org, o a mano) busca zonas nuevas con todas las cuentas de Apify, deja `PROSP_RESERVA_USD` para las tandas, sube el avance después de cada zona y rearma la lista. Ciudades: LA, Atlanta, Houston + Dallas, Phoenix, Miami, Tampa, Orlando, Charlotte, Nashville, San Antonio, Austin y Las Vegas (`PROSP_ZONAS`; cada ciudad necesita su zona horaria en `ZONAS_CIUDAD`). La lista guarda solo las prioridades de `PROSP_PRIORIDADES` (desde el 20/11/2026, solo A; si se suma B, entran solo los B con negativa sin responder). `datos/` queda como respaldo viejo.
- Stock justo (desde el 20/11/2026): `buscar` (y la Action) primero cuenta los A sin contactar y sin vencer; si llegan a `PROSP_STOCK_OBJETIVO` (100) no gasta nada, y si no, busca solo las zonas que faltan (según los A por zona medidos). `--forzar` busca igual. Cada prospecto lleva `datos_del` (fecha de los datos de su zona); pasados `PROSP_VENCE_DIAS` (45) la campaña no lo usa y su zona queda para volver a revisarse. Si un negocio aparece en dos bloques, gana el dato más nuevo.
- Orden de zonas (`zonas_pendientes`): primero las `PROSP_ZONAS_PRUEBA` primeras de cada ciudad sin probar, después las nuevas de las ciudades con más A por zona (`prospeccion/rendimiento.json`, lo escribe `lista`), y al final las bajadas hace más de `PROSP_REVISITAR_DIAS`. Búsqueda de mails (`emails.py`, `BUSQUEDA_VERSION`): hasta 4 páginas (contacto primero), mails escondidos ("[at]", mailto, Cloudflare, `\u0040`) y, al subir la versión, vuelve a mirar las webs sin mail sin perder nunca uno ya encontrado. También guarda señales para otros servicios (web móvil, https, vieja, reservas y pedidos online) y el nombre del dueño si la web lo dice; van como columnas al CSV. El nombre del dueño todavía no se usa en los mails; solo se acepta si es un nombre de pila conocido (gender-guesser; sin esa librería no se buscan y `BUSQUEDA_VERSION` queda en 2). El puntaje suma "dejó de responder" y "rating bajando".
- `estudio.py` es la herramienta del estudio de nichos inicial (ya cumplida): no se usa en el día a día.
- `credentials.json` y `token_gmail.json` (acceso a Gmail) nunca se leen, imprimen ni suben. En GitHub van como secretos de `radar-datos`.
- No se arman tandas en fin de semana ni en feriados de EEUU (Thanksgiving, Black Friday, Navidad, etc.), salvo con `--forzar`.
- Un solo negocio por dominio de empresa en toda la campaña.
- Si `registro.json` o `bajas.json` están rotos, el script frena. Hay copias locales en `datos/backups/`.
- Los tests (`tests/`) usan datos inventados: este repo es público, nunca poner datos reales ahí.
- Los mails salen como borradores y se revisan antes de mandarse. Firma: Lucas Pesqueira / Tinko Projects, con dirección postal y línea de baja.

## Comandos
- `py campana.py estado` — resumen de la campaña (con alertas)
- `py campana.py apify` — crédito libre de cada cuenta de Apify (prueba token_apify.txt, token_apify1.txt, token_apify2.txt... en orden y usa la primera con crédito; en la nube, el secreto APIFY_TOKEN puede tener varios, uno por renglón)
- `py campana.py destrabar` — destraba el freno de emergencia, después de revisar los rebotes o bajas
- `py prospectar.py estimar` / `buscar [--max N] [--si]` / `lista` / `migrar` — prospección (ver arriba)
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
- Plantillas del 22/11/2026 (`campana/plantillas.md` en radar-datos): el primer mail arranca por la reseña sin responder y ofrece la prueba gratis; el seguimiento 1 va sin precio; saludo con `negocio_corto` (`campana.nombre_corto`). `control.py` rechaza el primer mail sin "free" y las frases gastadas (`FRASES_GASTADAS`).
- Tope diario con subida gradual (`C.RAMPA`, `campana.limite_del_dia`): 25 desde el 23/11, 35 desde el 7/12 y 50 desde el 21/12, solo si en los últimos 14 días los primeros mails rebotaron menos de 3% y el freno no está activo; si no, queda un escalón abajo. El tope de cada día queda en diario.json (`tope`).
