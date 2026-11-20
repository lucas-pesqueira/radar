"""Configuración del estudio de nichos.

Todo lo que se puede ajustar sin tocar el resto del código está acá:
rubros, ciudades, tamaño de la muestra, precios de Apify y umbrales.
"""

# ---------------------------------------------------------------------------
# Rubros a comparar
# ---------------------------------------------------------------------------
# busqueda:   lo que se escribe en Google Maps (en inglés, como lo buscaría un cliente).
# categorias: palabras que tiene que tener alguna categoría de Google del negocio
#             para contar como de este rubro (filtra resultados que no son del rubro).
# excluir:    palabras que, si aparecen en la categoría principal, lo descartan
#             (por ejemplo, una tienda de insumos de plomería no es un plomero).
# ticket:     cuánto vale un cliente de ese rubro (alto / medio / bajo). Lo usa el
#             análisis final, no el script.
RUBROS = {
    "administradoras": {
        "nombre": "Administradoras de alquileres",
        "busqueda": "property management company",
        "categorias": ["property management"],
        "excluir": [],
        "ticket": "alto",
    },
    "mudanzas": {
        "nombre": "Mudanzas",
        "busqueda": "moving company",
        "categorias": ["moving company", "mover", "moving and storage"],
        "excluir": ["supply", "truck rental"],
        "ticket": "alto",
    },
    "electrodomesticos": {
        "nombre": "Reparación de electrodomésticos",
        "busqueda": "appliance repair",
        "categorias": ["appliance repair"],
        "excluir": ["parts", "store"],
        "ticket": "medio",
    },
    "plomeros": {
        "nombre": "Plomeros",
        "busqueda": "plumber",
        "categorias": ["plumber", "plumbing", "drainage", "water heater"],
        "excluir": ["supply", "store", "wholesaler"],
        "ticket": "alto",
    },
    "hvac": {
        "nombre": "HVAC (aire y calefacción)",
        "busqueda": "hvac contractor",
        "categorias": ["hvac", "air conditioning", "heating", "furnace"],
        "excluir": ["supply", "store", "wholesaler"],
        "ticket": "alto",
    },
    "plagas": {
        "nombre": "Control de plagas",
        "busqueda": "pest control",
        "categorias": ["pest control", "exterminator", "termite"],
        "excluir": ["store", "supply"],
        "ticket": "medio",
    },
    "garajes": {
        "nombre": "Puertas de garaje",
        "busqueda": "garage door repair",
        "categorias": ["garage door"],
        "excluir": [],
        "ticket": "medio",
    },
    "techistas": {
        "nombre": "Techistas",
        "busqueda": "roofing contractor",
        "categorias": ["roofing"],
        "excluir": ["supply", "store", "wholesaler"],
        "ticket": "alto",
    },
    "talleres": {
        "nombre": "Talleres mecánicos",
        "busqueda": "auto repair shop",
        "categorias": ["auto repair", "mechanic", "car repair", "brake", "transmission",
                       "auto tune", "engine rebuilding", "oil change"],
        "excluir": ["parts store", "dealer", "rental"],
        "ticket": "medio",
    },
    "chapa": {
        "nombre": "Chapa y pintura",
        "busqueda": "auto body shop",
        "categorias": ["body shop", "auto body", "collision", "auto painting", "dent"],
        "excluir": ["parts store", "dealer", "supply"],
        "ticket": "alto",
    },
    "unas": {
        "nombre": "Salones de uñas",
        "busqueda": "nail salon",
        "categorias": ["nail salon"],
        "excluir": ["supply", "store"],
        "ticket": "bajo",
    },
    "restaurantes": {
        "nombre": "Restaurantes independientes",
        "busqueda": "restaurant",
        "categorias": ["restaurant", "diner", "steak house", "bistro", "grill", "brewpub",
                       "gastropub", "eatery"],
        "excluir": ["supply", "store", "caterer", "shopping", "mall", "hotel", "market"],
        "ticket": "bajo",
    },
}

# ---------------------------------------------------------------------------
# Ciudades
# ---------------------------------------------------------------------------
CIUDADES = {
    "houston": {"nombre": "Houston, TX", "ubicacion": "Houston, Texas, USA"},
    "atlanta": {"nombre": "Atlanta, GA", "ubicacion": "Atlanta, Georgia, USA"},
    "los_angeles": {"nombre": "Los Angeles, CA", "ubicacion": "Los Angeles, California, USA"},
    "kansas_city": {"nombre": "Kansas City, MO", "ubicacion": "Kansas City, Missouri, USA"},
}

# ---------------------------------------------------------------------------
# Tamaño de la muestra
# ---------------------------------------------------------------------------
NEGOCIOS_POR_BUSQUEDA = 10   # por rubro y por ciudad -> 40 por rubro en total
RESENAS_POR_NEGOCIO = 8      # las más nuevas de cada negocio

# ---------------------------------------------------------------------------
# Apify
# ---------------------------------------------------------------------------
ACTOR_MAPS = "compass~crawler-google-places"

# Precios del plan gratis (USD por unidad), sacados de la página de precios del actor.
# "detalle" es un adicional que a veces se cobra al bajar reseñas: se cuenta siempre
# para calcular el peor caso y no pasarse del crédito.
PRECIOS = {
    "inicio": 0.00005,
    "lugar": 0.004,
    "detalle": 0.002,
    "resena": 0.0005,
}
PRESUPUESTO_USD = 5.00       # crédito mensual del plan gratis de Apify

# ---------------------------------------------------------------------------
# Umbrales del análisis
# ---------------------------------------------------------------------------
DIAS_RECIENTE = 90             # "sin responder reciente" = de los últimos 90 días
DIAS_NEGATIVA = 180            # negativa (1-2 estrellas) sin responder de los últimos 180 días
MIN_RESENAS_MUESTRA = 3        # mínimo de reseñas bajadas para medir la tasa de respuesta
POCAS_RESENAS = 20             # menos de esto en total = le sirve generar reseñas

# Prospecto calificado: independiente, perfil reclamado, abierto y con al menos una de:
#   - SIN_RESP_MIN reseñas sin responder en los últimos DIAS_RECIENTE días
#   - una negativa sin responder en los últimos DIAS_NEGATIVA días
# y que reciba al menos MIN_RESENAS_MES reseñas por mes (si no, no hay trabajo mensual).
SIN_RESP_MIN = 2
MIN_RESENAS_MES = 1.0

# ---------------------------------------------------------------------------
# Detección de cadenas y franquicias
# ---------------------------------------------------------------------------
# Un dominio web compartido por varios negocios en ciudades distintas, o por 3 o más
# negocios, se toma como cadena. Esta lista atrapa las marcas que aparecen una sola vez.
# Marcas de cadenas, por rubro: una marca solo descarta negocios de su propio rubro
# (así "Mayflower Seafood" no queda afuera por la mudanza Mayflower, ni "Rollins Realty" por la de plagas).
_OFICIOS = [
    "roto-rooter", "mr. rooter", "mr rooter", "benjamin franklin plumbing", "ars rescue rooter",
    "one hour heating", "aire serv", "mr. appliance", "mr appliance", "sears home services",
    "precision garage door", "precision door", "overhead door", "a1 garage door",
]
_TALLERES = [
    "firestone", "midas", "meineke", "pep boys", "jiffy lube", "valvoline", "goodyear",
    "christian brothers automotive", "monro", "mavis", "ntb", "tire kingdom", "discount tire",
    "caliber collision", "gerber collision", "service king", "crash champions", "maaco",
    "carstar", "fix auto", "take 5", "aamco", "big o tires", "les schwab", "brakes plus",
]
MARCAS_POR_RUBRO = {
    "mudanzas": ["two men and a truck", "u-haul", "uhaul", "pods", "college hunks", "allied van lines",
                 "united van lines", "mayflower", "atlas van lines", "bekins", "north american van lines",
                 "bellhop", "bellhops", "einstein moving"],
    "plomeros": _OFICIOS, "hvac": _OFICIOS, "electrodomesticos": _OFICIOS, "garajes": _OFICIOS,
    "plagas": ["terminix", "orkin", "rentokil", "truly nolen", "aptive", "mosquito joe", "mosquito squad",
               "arrow exterminators", "ehrlich", "western exterminator", "rollins"],
    "techistas": ["erie home"],
    "talleres": _TALLERES, "chapa": _TALLERES,
    "administradoras": ["greystar", "invitation homes", "progress residential", "real property management",
                        "mynd", "evernest", "american homes 4 rent", "tricon", "pathlight",
                        "main street renewal", "regency centers"],
    "unas": ["miniluxe"],
    "restaurantes": [
        # hoteles (restaurantes dentro de hoteles)
        "wyndham", "marriott", "hilton", "hyatt", "sheraton", "westin", "radisson",
        "holiday inn", "best western", "la quinta", "embassy suites", "doubletree",
        # cadenas de comida
        "mcdonald's", "burger king", "wendy's", "taco bell", "chick-fil-a", "subway", "popeyes",
        "kfc", "domino's", "pizza hut", "papa john's", "little caesars", "applebee's",
        "chili's", "olive garden", "ihop", "denny's", "waffle house", "cracker barrel",
        "texas roadhouse", "outback", "red lobster", "buffalo wild wings", "panda express",
        "chipotle", "whataburger", "sonic drive-in", "jack in the box", "in-n-out",
        "cheesecake factory", "p.f. chang", "red robin", "five guys", "panera", "starbucks",
        "sugarfish",
    ],
}
MARCAS_GENERALES = ["home depot", "lowe's", "lowes"]          # valen para cualquier rubro
MARCAS_CADENA = sorted({m for ms in MARCAS_POR_RUBRO.values() for m in ms} | set(MARCAS_GENERALES))

# Sitios que no son una web propia (redes, directorios, mapas).
HOSTS_NO_WEB = [
    "facebook.com", "fb.com", "instagram.com", "linktr.ee", "yelp.com", "x.com",
    "twitter.com", "tiktok.com", "youtube.com", "nextdoor.com", "google.com", "g.page",
    "goo.gl", "linkedin.com", "angi.com", "homeadvisor.com", "thumbtack.com", "bbb.org",
    "doordash.com", "ubereats.com", "grubhub.com", "toasttab.com", "opentable.com",
    "yellowpages.com", "booksy.com", "vagaro.com", "styleseat.com", "fresha.com",
]

# Constructores de webs donde cada negocio tiene su subdominio: se compara el host
# completo y no el dominio (si no, todos los sitios de Wix parecerían una cadena).
HOSTS_CONSTRUCTOR = [
    "wixsite.com", "business.site", "square.site", "godaddysites.com", "weebly.com",
    "wordpress.com", "squarespace.com", "myshopify.com", "webflow.io", "carrd.co",
    "sites.google.com", "ueniweb.com", "site123.me", "jimdosite.com",
]

# ===========================================================================
# MODO PROSPECCIÓN
# ===========================================================================
PROSP_RUBROS = ["administradoras", "mudanzas", "restaurantes", "unas"]

# Cada ciudad se recorre por zonas (barrios y ciudades del área), así cada búsqueda
# trae negocios nuevos y no se paga dos veces por el mismo. Se hacen en orden,
# alternando ciudades. Cada texto es la ubicación tal cual se busca en Google Maps.
PROSP_ZONAS = {
    "los_angeles": [
        "Downtown, Los Angeles, California, USA",
        "Koreatown, Los Angeles, California, USA",
        "Hollywood, Los Angeles, California, USA",
        "Silver Lake, Los Angeles, California, USA",
        "Echo Park, Los Angeles, California, USA",
        "Los Feliz, Los Angeles, California, USA",
        "Mid-Wilshire, Los Angeles, California, USA",
        "Westwood, Los Angeles, California, USA",
        "Venice, Los Angeles, California, USA",
        "Mar Vista, Los Angeles, California, USA",
        "Palms, Los Angeles, California, USA",
        "Brentwood, Los Angeles, California, USA",
        "Highland Park, Los Angeles, California, USA",
        "Eagle Rock, Los Angeles, California, USA",
        "Boyle Heights, Los Angeles, California, USA",
        "West Adams, Los Angeles, California, USA",
        "Westchester, Los Angeles, California, USA",
        "San Pedro, Los Angeles, California, USA",
        "Studio City, Los Angeles, California, USA",
        "Sherman Oaks, Los Angeles, California, USA",
        "Encino, Los Angeles, California, USA",
        "Van Nuys, Los Angeles, California, USA",
        "North Hollywood, Los Angeles, California, USA",
        "Woodland Hills, Los Angeles, California, USA",
        "Northridge, Los Angeles, California, USA",
        "Chatsworth, Los Angeles, California, USA",
    ],
    "atlanta": [
        "Downtown, Atlanta, Georgia, USA",
        "Midtown, Atlanta, Georgia, USA",
        "Buckhead, Atlanta, Georgia, USA",
        "Old Fourth Ward, Atlanta, Georgia, USA",
        "Inman Park, Atlanta, Georgia, USA",
        "Virginia-Highland, Atlanta, Georgia, USA",
        "West Midtown, Atlanta, Georgia, USA",
        "Grant Park, Atlanta, Georgia, USA",
        "East Atlanta, Atlanta, Georgia, USA",
        "Kirkwood, Atlanta, Georgia, USA",
        "Decatur, Georgia, USA",
        "Brookhaven, Georgia, USA",
        "Sandy Springs, Georgia, USA",
        "Dunwoody, Georgia, USA",
        "Smyrna, Georgia, USA",
        "Marietta, Georgia, USA",
        "East Point, Georgia, USA",
        "College Park, Georgia, USA",
        "Chamblee, Georgia, USA",
        "Tucker, Georgia, USA",
    ],
    "houston": [
        "Downtown, Houston, Texas, USA",
        "Midtown, Houston, Texas, USA",
        "Montrose, Houston, Texas, USA",
        "The Heights, Houston, Texas, USA",
        "River Oaks, Houston, Texas, USA",
        "Uptown, Houston, Texas, USA",
        "Memorial, Houston, Texas, USA",
        "Westchase, Houston, Texas, USA",
        "Energy Corridor, Houston, Texas, USA",
        "Texas Medical Center, Houston, Texas, USA",
        "Third Ward, Houston, Texas, USA",
        "East End, Houston, Texas, USA",
        "Spring Branch, Houston, Texas, USA",
        "Meyerland, Houston, Texas, USA",
        "Bellaire, Texas, USA",
        "Pasadena, Texas, USA",
        "Katy, Texas, USA",
        "Sugar Land, Texas, USA",
        "Pearland, Texas, USA",
        "Kingwood, Texas, USA",
        "Cypress, Texas, USA",
        "Spring, Texas, USA",
        "Humble, Texas, USA",
        "The Woodlands, Texas, USA",
    ],
    # Ciudades nuevas (desde el 20/11/2026): metros del sur con mucho comercio chico.
    "dallas": [
        "Downtown, Dallas, Texas, USA",
        "Uptown, Dallas, Texas, USA",
        "Deep Ellum, Dallas, Texas, USA",
        "Bishop Arts District, Dallas, Texas, USA",
        "Lower Greenville, Dallas, Texas, USA",
        "Lakewood, Dallas, Texas, USA",
        "Oak Lawn, Dallas, Texas, USA",
        "Preston Hollow, Dallas, Texas, USA",
        "Plano, Texas, USA",
        "Richardson, Texas, USA",
        "Irving, Texas, USA",
        "Garland, Texas, USA",
        "Frisco, Texas, USA",
        "Addison, Texas, USA",
        "Carrollton, Texas, USA",
        "Arlington, Texas, USA",
        "Fort Worth, Texas, USA",
    ],
    "phoenix": [
        "Downtown, Phoenix, Arizona, USA",
        "Arcadia, Phoenix, Arizona, USA",
        "Midtown, Phoenix, Arizona, USA",
        "Ahwatukee, Phoenix, Arizona, USA",
        "Desert Ridge, Phoenix, Arizona, USA",
        "Scottsdale, Arizona, USA",
        "Tempe, Arizona, USA",
        "Mesa, Arizona, USA",
        "Chandler, Arizona, USA",
        "Gilbert, Arizona, USA",
        "Glendale, Arizona, USA",
        "Peoria, Arizona, USA",
        "Surprise, Arizona, USA",
    ],
    "miami": [
        "Downtown, Miami, Florida, USA",
        "Brickell, Miami, Florida, USA",
        "Wynwood, Miami, Florida, USA",
        "Little Havana, Miami, Florida, USA",
        "Coconut Grove, Miami, Florida, USA",
        "Coral Gables, Florida, USA",
        "Miami Beach, Florida, USA",
        "Doral, Florida, USA",
        "Hialeah, Florida, USA",
        "Kendall, Florida, USA",
        "Aventura, Florida, USA",
        "North Miami, Florida, USA",
        "Fort Lauderdale, Florida, USA",
        "Hollywood, Florida, USA",
    ],
    "tampa": [
        "Downtown, Tampa, Florida, USA",
        "Ybor City, Tampa, Florida, USA",
        "Hyde Park, Tampa, Florida, USA",
        "Seminole Heights, Tampa, Florida, USA",
        "Westshore, Tampa, Florida, USA",
        "Carrollwood, Tampa, Florida, USA",
        "Brandon, Florida, USA",
        "Clearwater, Florida, USA",
        "St. Petersburg, Florida, USA",
        "Largo, Florida, USA",
        "Wesley Chapel, Florida, USA",
        "Riverview, Florida, USA",
    ],
    "orlando": [
        "Downtown, Orlando, Florida, USA",
        "Thornton Park, Orlando, Florida, USA",
        "Mills 50, Orlando, Florida, USA",
        "College Park, Orlando, Florida, USA",
        "Dr. Phillips, Orlando, Florida, USA",
        "Lake Nona, Orlando, Florida, USA",
        "Winter Park, Florida, USA",
        "Kissimmee, Florida, USA",
        "Altamonte Springs, Florida, USA",
        "Winter Garden, Florida, USA",
        "Oviedo, Florida, USA",
        "Sanford, Florida, USA",
        "Lake Mary, Florida, USA",
        "Apopka, Florida, USA",
    ],
    "charlotte": [
        "Uptown, Charlotte, North Carolina, USA",
        "South End, Charlotte, North Carolina, USA",
        "NoDa, Charlotte, North Carolina, USA",
        "Plaza Midwood, Charlotte, North Carolina, USA",
        "Dilworth, Charlotte, North Carolina, USA",
        "Myers Park, Charlotte, North Carolina, USA",
        "Ballantyne, Charlotte, North Carolina, USA",
        "SouthPark, Charlotte, North Carolina, USA",
        "University City, Charlotte, North Carolina, USA",
        "Matthews, North Carolina, USA",
        "Huntersville, North Carolina, USA",
        "Concord, North Carolina, USA",
        "Gastonia, North Carolina, USA",
        "Cornelius, North Carolina, USA",
    ],
    "nashville": [
        "Downtown, Nashville, Tennessee, USA",
        "The Gulch, Nashville, Tennessee, USA",
        "East Nashville, Nashville, Tennessee, USA",
        "Midtown, Nashville, Tennessee, USA",
        "12 South, Nashville, Tennessee, USA",
        "Germantown, Nashville, Tennessee, USA",
        "Sylvan Park, Nashville, Tennessee, USA",
        "Green Hills, Nashville, Tennessee, USA",
        "Antioch, Nashville, Tennessee, USA",
        "Donelson, Nashville, Tennessee, USA",
        "Franklin, Tennessee, USA",
        "Brentwood, Tennessee, USA",
        "Murfreesboro, Tennessee, USA",
        "Hendersonville, Tennessee, USA",
    ],
    "san_antonio": [
        "Downtown, San Antonio, Texas, USA",
        "Southtown, San Antonio, Texas, USA",
        "Alamo Heights, San Antonio, Texas, USA",
        "Stone Oak, San Antonio, Texas, USA",
        "Medical Center, San Antonio, Texas, USA",
        "Pearl District, San Antonio, Texas, USA",
        "Leon Valley, Texas, USA",
        "Helotes, Texas, USA",
        "New Braunfels, Texas, USA",
        "Schertz, Texas, USA",
        "Converse, Texas, USA",
        "Live Oak, Texas, USA",
        "Universal City, Texas, USA",
    ],
    "austin": [
        "Downtown, Austin, Texas, USA",
        "South Congress, Austin, Texas, USA",
        "East Austin, Austin, Texas, USA",
        "Hyde Park, Austin, Texas, USA",
        "Mueller, Austin, Texas, USA",
        "Zilker, Austin, Texas, USA",
        "North Loop, Austin, Texas, USA",
        "Round Rock, Texas, USA",
        "Cedar Park, Texas, USA",
        "Pflugerville, Texas, USA",
        "Georgetown, Texas, USA",
        "Leander, Texas, USA",
        "Lakeway, Texas, USA",
        "Kyle, Texas, USA",
    ],
    "las_vegas": [
        "Downtown, Las Vegas, Nevada, USA",
        "Summerlin, Las Vegas, Nevada, USA",
        "Spring Valley, Las Vegas, Nevada, USA",
        "Chinatown, Las Vegas, Nevada, USA",
        "Centennial Hills, Las Vegas, Nevada, USA",
        "Enterprise, Las Vegas, Nevada, USA",
        "Henderson, Nevada, USA",
        "North Las Vegas, Nevada, USA",
        "Boulder City, Nevada, USA",
    ],
}

# Nombre de las ciudades de la prospección que no estaban en el estudio de nichos.
CIUDADES_PROSP = {
    "dallas": {"nombre": "Dallas, TX"},
    "phoenix": {"nombre": "Phoenix, AZ"},
    "miami": {"nombre": "Miami, FL"},
    "tampa": {"nombre": "Tampa, FL"},
    "orlando": {"nombre": "Orlando, FL"},
    "charlotte": {"nombre": "Charlotte, NC"},
    "nashville": {"nombre": "Nashville, TN"},
    "san_antonio": {"nombre": "San Antonio, TX"},
    "austin": {"nombre": "Austin, TX"},
    "las_vegas": {"nombre": "Las Vegas, NV"},
}
TODAS_CIUDADES = {**CIUDADES_PROSP, **CIUDADES}

# Qué prioridades quedan en la lista. Desde el 20/11/2026 solo A (lo más exigente);
# si salen muy pocos, se puede sumar "B" (y en prospectar se guardan solo los B con negativa).
PROSP_PRIORIDADES = ["A"]
PROSP_RESERVA_USD = 3.00           # crédito de Apify (sumando todas las cuentas) que la prospección deja para las tandas
PROSP_MAX_ZONAS = 15               # zonas por corrida automática (la Action se puede correr con otro número)
CAIDA_RATING = 0.7                 # últimas reseñas este tanto por debajo del rating general = "rating bajando"
PROSP_ZONAS_PRUEBA = 2             # zonas que se prueban en cada ciudad antes de priorizar por rendimiento
# Stock justo (Plan 1 + 3, 20/11/2026): se busca solo lo que falta para tener unas 2 semanas de envíos,
# y los prospectos con datos más viejos que PROSP_VENCE_DIAS no se usan (su zona se vuelve a revisar).
PROSP_STOCK_OBJETIVO = 100         # A sin contactar (y sin vencer) que se quieren tener
PROSP_A_POR_ZONA = 6               # A que deja una zona, si todavía no hay datos propios (rendimiento.json)
PROSP_VENCE_DIAS = 45              # días desde que se bajaron los datos del negocio
PROSP_REVISITAR_DIAS = PROSP_VENCE_DIAS   # una zona se vuelve a revisar pasados estos días (después de las nuevas)

PROSP_NEGOCIOS_POR_BUSQUEDA = 20   # por rubro y por zona
PROSP_RESENAS_POR_NEGOCIO = 5      # alcanzan para ver si responde y encontrar el gancho
PROSP_MARGEN_USD = 0.10            # crédito que se deja sin usar por las dudas

# Filtros del prospecto
PROSP_MIN_RESENAS_TOTALES = 5      # con menos, no hay qué responder
PROSP_MAX_RESENAS_TOTALES = 2000   # con más, suelen tener equipo o agencia propia
# Prioridad A = prospecto calificado (ver arriba). B = al menos 1 reseña sin
# responder en DIAS_RECIENTE días o una negativa sin responder.

# Si responde al menos esta proporción de sus reseñas, ya se ocupa: queda en prioridad B.
PROSP_TASA_MAX_A = 0.75

# Palabras que delatan una reseña de 1-2 estrellas escrita en positivo (el cliente
# se equivocó al puntuar): ese gancho se marca como dudoso.
PALABRAS_POSITIVAS = [
    "great", "amazing", "excellent", "awesome", "best", "love", "loved", "perfect",
    "fantastic", "delicious", "recommend", "10/10", "wonderful", "very good", "so good",
]
# Si además tiene alguna de estas, la reseña es negativa de verdad (no un error de puntaje).
PALABRAS_NEGATIVAS = [
    "not", "n't", "never", "bad", "terrible", "horrible", "worst", "rude", "poor", "awful",
    "dirty", "disappoint", "unprofessional", "waste", "scam", "late", "damage", "broke",
    "sick", "poison", "infection", "refund", "overcharg", "ripped", "avoid", "beware",
    "careful", "ignored", "unacceptable", "nasty", "cold", "slow", "wrong", "problem",
]

# ===========================================================================
# CAMPAÑA DE MAILS
# ===========================================================================
ENVIOS_POR_DIA = 25              # total por casilla y por día, contando seguimientos
SEGUIMIENTO_DIAS = (3, 7)        # días hábiles desde el primer mail para cada seguimiento
VERIFICAR_RESENAS = 5            # reseñas que se vuelven a bajar para chequear el gancho
PRECIO_RUBRO = {                 # precio de fundador en USD por mes
    "administradoras": 99, "mudanzas": 99, "restaurantes": 59, "unas": 59,
}
VERIFICAR_RONDAS = 4             # máximo de corridas de Apify por tanda para completar el cupo

# Horario de envío: cada mail sale cerca de las 10 de la mañana en la ciudad del destinatario.
ZONAS_CIUDAD = {                 # palabra en el nombre de la ciudad -> zona horaria
    "atlanta": "America/New_York",
    "houston": "America/Chicago",
    "los angeles": "America/Los_Angeles",
    "dallas": "America/Chicago",
    "phoenix": "America/Phoenix",       # Arizona no cambia de hora en verano
    "miami": "America/New_York",
    "tampa": "America/New_York",
    "orlando": "America/New_York",
    "charlotte": "America/New_York",
    "nashville": "America/Chicago",
    "san antonio": "America/Chicago",
    "austin": "America/Chicago",
    "las vegas": "America/Los_Angeles",
}
ZONA_LUCAS = "America/Argentina/Buenos_Aires"
HORA_LOCAL_ENVIO = 10            # primer mail de cada ciudad a esta hora local
SEPARACION_MIN = (11, 17)        # minutos entre un mail y el siguiente de la misma ciudad (al azar)

# False: los mails los manda enviar.py (GitHub Actions) y los marca como enviados al mandarlos.
# True solo si se vuelve a programar a mano en Gmail: lo armado se da por enviado al día siguiente.
CONFIRMAR_AL_DIA_SIGUIENTE = False

# ---------------------------------------------------------------------------
# Controles de la campaña automática (control.py)
# ---------------------------------------------------------------------------
FRENO_DESDE = "2026-11-23"       # el freno cuenta solo lo enviado desde esta fecha (los rebotes viejos ya se trataron)
FRENO_REBOTES = (2, 30)          # más de 2 rebotes en los últimos 30 primeros mails -> se frenan los primeros mails
FRENO_BAJAS_DIA = 2              # más de 2 bajas en un mismo día -> se frenan los primeros mails
ALERTA_STOCK_AB = 150            # avisar cuando queden menos prospectos A/B sin contactar
ALERTA_CREDITO_DIAS = 5          # avisar cuando el crédito de Apify alcance para menos tandas
ALERTA_TANDA_MIN = 15            # avisar si una tanda sale con menos primeros mails que esto
