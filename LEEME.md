# Radar — estudio de nichos

Compara 12 rubros en 4 ciudades de EEUU y mide en cuáles hay más negocios
independientes con reseñas de Google sin responder. Sale una tabla por rubro,
otra por ciudad, el cruce rubro × ciudad y la lista de negocios con su puntaje.

## Qué hace cada paso

| Comando | Qué hace | Cuesta |
|---|---|---|
| `py estudio.py estimar` | Calcula el gasto máximo y muestra tu crédito de Apify | Nada |
| `py estudio.py descargar` | Baja 10 negocios por rubro y ciudad con sus 8 reseñas más nuevas | Hasta USD 4,80 del crédito gratis |
| `py estudio.py emails` | Busca el mail público en la web de cada negocio | Nada |
| `py estudio.py analizar` | Arma las tablas y el reporte | Nada |
| `py estudio.py todo` | Los tres últimos seguidos | Hasta USD 4,80 |

- Lo descargado queda guardado en `datos/`. Si lo volvés a correr, no paga de nuevo.
- Si cortás la descarga a la mitad, la corrida sigue en Apify: volvé a correr `descargar` y la retoma.
- `analizar` se puede repetir todas las veces que quieras, por ejemplo después de cambiar umbrales en `config.py`.

## Resultados

Quedan en `resultados/<fecha>/`:

- `reporte.html`: el resumen para mirar en el navegador.
- `rubros.csv`, `ciudades.csv`, `rubro_ciudad.csv`: las métricas.
- `negocios.csv`: cada negocio con su puntaje, por qué, y el gancho para el mail.

## No compartas

`token_apify.txt` es tu clave de Apify. No lo subas a GitHub ni lo mandes a nadie.

---

# Modo prospección

Arma la lista de negocios para contactar en los 4 rubros elegidos (administradoras,
mudanzas, restaurantes y uñas) en Los Ángeles, Atlanta y Houston.

| Comando | Qué hace | Cuesta |
|---|---|---|
| `py prospectar.py estimar` | Cuántas zonas alcanza a revisar tu crédito | Nada |
| `py prospectar.py buscar` | Revisa las zonas que faltan, hasta donde alcance el crédito | Tu crédito de Apify (USD 0,68 por zona como máximo) |
| `py prospectar.py lista` | Busca los mails y arma la lista | Nada |

- Cada ciudad se recorre por barrios y ciudades del área, alternando. Nunca repite una zona.
- Usa también lo que ya bajó el estudio, sin pagarlo de nuevo.
- Correlo una vez por mes, cuando se recarga el crédito: sigue con las zonas que faltan.

## La lista

Queda en `prospectos/`:

- `prospectos_todos.csv`: todos los prospectos encontrados hasta ahora.
- `prospectos_nuevos_<fecha>.csv`: solo los que no estaban en listas anteriores. Es la que se carga para mandar mails.

Cada fila trae el mail, la prioridad (A = señal fuerte, B = señal más leve), el puntaje
y el **gancho**: la reseña que conviene responder gratis en el primer mail (la negativa
sin responder más nueva o, si no hay, la sin responder más nueva), con el nombre de
pila de quien la escribió para saludarlo en la respuesta.
