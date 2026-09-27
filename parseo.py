import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

import tiempo

SIN_CLASIFICAR = "Sin clasificar"

# Categorías que vienen de fábrica. El usuario puede agregar las suyas (ver db.categorias).
CATEGORIAS_BASE = [
    "Comida",
    "Mercado",
    "Delivery",
    "Transporte",
    "Salud",
    "Servicios",
    "Hogar",
    "Educación",
    "Ropa y calzado",
    "Cuidado personal",
    "Mascotas",
    "Regalos y familia",
    "Ocio",
    "Trámites y multas",
    "Ahorro y juntas",
    "Deudas",
    SIN_CLASIFICAR,
]

CATEGORIAS_INGRESO_BASE = [
    "Sueldo",
    "Ventas y cachuelos",
    "Regalos y apoyo",
    "Cobro de deudas",
    SIN_CLASIFICAR,
]

# El orden importa: la primera categoría con coincidencia gana
# ("delivery pollo 30" es Delivery, no Comida; "comida de perro" es Mascotas).
PALABRAS_CLAVE = {
    "Mascotas": [
        "perro", "perros", "gato", "gatos", "veterinario", "veterinaria", "mascota",
        "mascotas", "purina",
    ],
    "Delivery": [
        "delivery", "rappi", "pedidosya", "pedidos ya", "glovo", "didi food",
        "ubereats", "uber eats",
    ],
    "Transporte": [
        "combi", "coaster", "taxi", "bus", "micro", "metropolitano", "tren",
        "uber", "cabify", "indriver", "pasaje", "gasolina", "petroleo", "gnv",
        "mototaxi", "moto", "peaje", "estacionamiento", "cochera", "cobrador", "soat",
    ],
    "Salud": [
        "farmacia", "inkafarma", "mifarma", "botica", "medicina", "pastilla",
        "doctor", "consulta", "clinica", "dentista", "analisis", "examen medico",
    ],
    "Servicios": [
        "luz", "agua", "gas", "internet", "wifi", "celular", "recarga", "claro",
        "movistar", "entel", "bitel", "sedapal", "enel", "luz del sur", "cable",
    ],
    "Hogar": [
        "alquiler", "renta", "limpieza", "detergente", "lavanderia", "ferreteria",
        "mueble", "reparacion", "gasfitero", "electricista",
    ],
    "Educación": [
        "pension", "matricula", "libro", "curso", "copias", "fotocopias",
        "utiles", "universidad", "colegio", "taller",
    ],
    "Trámites y multas": [
        "tramite", "multa", "papeleo", "dni", "pasaporte", "notaria", "sunat",
        "reniec", "licencia", "partida", "certificado",
    ],
    "Deudas": [
        "deuda", "cuota", "prestamo", "tarjeta de credito", "cmr",
    ],
    "Ahorro y juntas": [
        "ahorro", "ahorre", "junta", "pandero", "alcancia", "fondo de emergencia",
    ],
    "Ropa y calzado": [
        "ropa", "polo", "polera", "pantalon", "jean", "zapatillas", "zapatilla",
        "zapatos", "zapato", "calzado", "casaca", "camisa", "vestido", "medias",
    ],
    "Cuidado personal": [
        "peluqueria", "peluquero", "barberia", "barbero", "corte de pelo", "jabon",
        "shampoo", "desodorante", "pasta dental", "cepillo", "papel higienico",
        "afeitar", "manicure", "maquillaje", "perfume",
    ],
    "Regalos y familia": [
        "regalo", "regalos", "cumpleanos", "mesada", "apoyo", "dia de la madre",
        "dia del padre",
    ],
    "Ocio": [
        "cine", "netflix", "spotify", "disney", "hbo", "prime", "youtube",
        "salida", "cerveza", "chela", "chelas", "bar", "discoteca", "fiesta",
        "concierto", "juego", "steam", "playstation", "karaoke", "trago",
        "pisco", "suscripcion", "claude", "chatgpt", "openai", "canva",
        "gimnasio", "gym", "cancha", "partido", "futbol", "voley", "basquet",
        "polideportivo", "deporte", "fulbito",
    ],
    "Mercado": [
        "mercado", "bodega", "super", "supermercado", "wong", "plazavea",
        "plaza vea", "tottus", "vivanda", "metro", "makro", "verduras",
        "frutas", "carne", "pollo crudo", "abarrotes", "compras",
    ],
    "Comida": [
        "almuerzo", "desayuno", "cena", "cenar", "menu", "chifa", "pollo",
        "polleria", "cafe", "cafeteria", "pan", "panaderia", "snack", "helado",
        "pizza", "hamburguesa", "sandwich", "ceviche", "anticucho", "salchipapa",
        "jugo", "gaseosa", "restaurante", "comida", "lonche", "cevicheria",
        "pollada", "chicha", "empanada", "tamal", "broaster", "sushi",
    ],
}

PALABRAS_INGRESO = {
    "Sueldo": [
        "sueldo", "salario", "quincena", "gratificacion", "cts", "utilidades",
        "bono", "adelanto",
    ],
    "Ventas y cachuelos": [
        "venta", "vendi", "cachuelo", "chamba", "propina", "comision", "trabajito",
    ],
    "Regalos y apoyo": [
        "regalo", "regalaron", "apoyo", "mesada",
    ],
}

PALABRAS_SUELTAS = {
    "de", "del", "la", "las", "el", "los", "un", "una", "unos", "unas", "con", "por",
    "para", "en", "y", "a", "al", "mi", "mis", "tu", "su", "que", "soles", "sol",
}

TIPOS = ("gasto", "ingreso", "me_deben", "debo")
MAX_MONTO_CENTIMOS = 10_000_000 * 100
MAX_PIEZAS = 10


class ErrorParser(ValueError):
    pass


@dataclass
class Movimiento:
    tipo: str
    concepto: str
    monto_centimos: int
    categoria: str
    fecha: date | None = None  # None = hoy
    persona: str | None = None
    dudosa: bool = False  # no supimos en qué categoría va: hay que preguntar


def normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFD", texto.lower())
    sin_tildes = "".join(c for c in sin_tildes if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", sin_tildes).strip()


_normalizar = normalizar


def _buscar(palabra: str, texto_normalizado: str) -> bool:
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(palabra)}(?:s|es)?(?![a-z0-9])", texto_normalizado))


# ---------- Monto ----------

# Monto con prefijo S/ (más fiable) o número suelto. Acepta 18, 18.5, 18,50, 1,250.00.
_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:[.,]\d{1,2})?"
_CON_PREFIJO = re.compile(rf"(?<![\w.,])s\s*/\s*\.?\s*({_NUM})(?![\w])", re.IGNORECASE)
_NUMERO = re.compile(rf"(?<![\w.,])({_NUM})(?![\w])")


def _a_decimal(token: str) -> Decimal:
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?", token):
        token = token.replace(",", "")
    else:
        token = token.replace(",", ".")
    return Decimal(token)


def _extraer_monto(texto: str):
    coincidencias = list(_CON_PREFIJO.finditer(texto))
    if not coincidencias:
        coincidencias = list(_NUMERO.finditer(texto))
    if not coincidencias:
        raise ErrorParser("No encontré un monto. Ejemplo: almuerzo 18")
    elegida = coincidencias[-1]
    try:
        monto = _a_decimal(elegida.group(1))
    except InvalidOperation:
        raise ErrorParser("No pude leer el monto.")
    if monto <= 0:
        raise ErrorParser("El monto debe ser mayor a cero.")
    centimos = int((monto * 100).to_integral_value())
    if centimos > MAX_MONTO_CENTIMOS:
        raise ErrorParser("El monto es demasiado grande.")
    return centimos, elegida.span()


# ---------- Fecha ----------

_FECHA_DM = [
    re.compile(r"\b(?:el|del)\s+(?P<d>\d{1,2})/(?P<m>\d{1,2})(?:/(?P<a>\d{2,4}))?\b", re.IGNORECASE),
    re.compile(r"\b(?P<d>\d{1,2})/(?P<m>\d{1,2})/(?P<a>\d{2,4})\b"),
    # 15/09 sí; 1/2 no (es media porción: "1/2 pollo")
    re.compile(r"\b(?P<d>\d{2})/(?P<m>\d{2})\b"),
]
_FECHA_HACE = re.compile(r"\bhace\s+(\d{1,2})\s+d[ií]as?\b", re.IGNORECASE)
_FECHA_ANTEAYER = re.compile(r"\bantes\s+de\s+ayer\b|\banteayer\b|\bantier\b", re.IGNORECASE)
_FECHA_AYER = re.compile(r"\bayer\b", re.IGNORECASE)
_FECHA_HOY = re.compile(r"\bhoy\b", re.IGNORECASE)
_FECHA_EL_DIA = re.compile(r"\b(?:el|del)\s+(?:d[ií]a\s+)?(?P<d>\d{1,2})\b(?![.,/]\d)", re.IGNORECASE)


def _crear_fecha(anio: int, mes: int, dia: int) -> date:
    try:
        return date(anio, mes, dia)
    except ValueError:
        raise ErrorParser("Esa fecha no existe.")


def _cortar(texto: str, m: re.Match) -> str:
    return (texto[: m.start()] + " " + texto[m.end():]).strip()


def _extraer_fecha(texto: str, hoy: date):
    """Devuelve (fecha o None, texto sin la expresión de fecha)."""
    for patron in _FECHA_DM:
        m = patron.search(texto)
        if not m:
            continue
        dia, mes = int(m.group("d")), int(m.group("m"))
        anio_txt = m.groupdict().get("a")
        if anio_txt:
            anio = int(anio_txt) + (2000 if len(anio_txt) == 2 else 0)
            fecha = _crear_fecha(anio, mes, dia)
        else:
            fecha = _crear_fecha(hoy.year, mes, dia)
            if fecha > hoy:
                fecha = _crear_fecha(hoy.year - 1, mes, dia)
        return fecha, _cortar(texto, m)

    for patron, dias in ((_FECHA_ANTEAYER, 2), (_FECHA_AYER, 1), (_FECHA_HOY, 0)):
        m = patron.search(texto)
        if m:
            return hoy - timedelta(days=dias), _cortar(texto, m)

    m = _FECHA_HACE.search(texto)
    if m:
        return hoy - timedelta(days=int(m.group(1))), _cortar(texto, m)

    m = _FECHA_EL_DIA.search(texto)
    if m:
        dia = int(m.group("d"))
        if dia < 1 or dia > 31:
            raise ErrorParser("Esa fecha no existe.")
        if dia <= hoy.day:
            fecha = _crear_fecha(hoy.year, hoy.month, dia)
        else:
            anio, mes = (hoy.year - 1, 12) if hoy.month == 1 else (hoy.year, hoy.month - 1)
            fecha = _crear_fecha(anio, mes, dia)
        return fecha, _cortar(texto, m)

    return None, texto


# ---------- Tipo y categoría ----------

_RE_ME_DEBEN = re.compile(r"(?<![a-z0-9])(?:le\s+)?preste(?![a-z0-9])")
_RE_DEBO = re.compile(r"(?<![a-z0-9])(?:le\s+)?debo(?![a-z0-9])|(?<![a-z0-9])fiado(?![a-z0-9])|(?<![a-z0-9])me\s+(?:fiaron|prestaron)(?![a-z0-9])")
_RE_INGRESO = re.compile(
    r"(?<![a-z0-9])(?:sueldo|salario|ingresos?|cobre|propinas?|cachuelos?|ventas?|vendi|bono|"
    r"gratificacion|cts|utilidades|comision(?:es)?|quincena|chamba|adelanto|me\s+pagaron|"
    r"me\s+depositaron|me\s+dieron|pago\s+recibido)(?![a-z0-9])"
)
_LIMPIA_PERSONA = re.compile(
    r"(?:le\s+)?(?:prest[eé]|debo|fiado|me\s+fiaron|me\s+prestaron)", re.IGNORECASE
)


def _por_palabras(reglas: dict, normalizado: str) -> str | None:
    for categoria, palabras in reglas.items():
        if any(_buscar(p, normalizado) for p in palabras):
            return categoria
    return None


def tokens_significativos(concepto: str) -> list[str]:
    """Palabras que identifican un gasto (sin conectores ni números). Sirven para aprender."""
    vistos: list[str] = []
    for t in re.findall(r"[a-z0-9]+", normalizar(concepto)):
        if len(t) < 3 or t.isdigit() or t in PALABRAS_SUELTAS or t in vistos:
            continue
        vistos.append(t)
    return vistos[:4]


def clasificar(tipo: str, concepto: str, aprendida=None) -> tuple[str, bool]:
    """(categoría, dudosa). Primero lo que el usuario enseñó, luego las reglas de fábrica.

    `aprendida(tipo, tokens)` devuelve la categoría que el usuario eligió antes para esas
    palabras, o None. Si nada coincide, la categoría es "Sin clasificar" y `dudosa` es True.
    """
    if aprendida:
        elegida = aprendida(tipo, tokens_significativos(concepto))
        if elegida:
            return elegida, False
    reglas = PALABRAS_INGRESO if tipo == "ingreso" else PALABRAS_CLAVE
    categoria = _por_palabras(reglas, normalizar(concepto))
    return (categoria, False) if categoria else (SIN_CLASIFICAR, True)


def _limpiar_concepto(concepto: str) -> str:
    concepto = re.sub(r"\s+", " ", concepto).strip()
    concepto = re.sub(r"^(?:de|en|por)\s+|\s+(?:soles|sol)$", "", concepto, flags=re.IGNORECASE).strip()
    return concepto


def _parsear_pieza(texto: str, hoy: date, aprendida=None) -> Movimiento:
    texto = (texto or "").strip()
    if not texto:
        raise ErrorParser("Escribe algo, por ejemplo: almuerzo 18")

    es_ingreso_por_signo = texto.startswith("+")
    if es_ingreso_por_signo:
        texto = texto[1:].strip()

    fecha, texto = _extraer_fecha(texto, hoy)
    centimos, (ini, fin) = _extraer_monto(texto)
    concepto = _limpiar_concepto(texto[:ini] + " " + texto[fin:])
    normalizado = _normalizar(concepto)

    if _RE_ME_DEBEN.search(normalizado) or _RE_DEBO.search(normalizado):
        tipo = "me_deben" if _RE_ME_DEBEN.search(normalizado) else "debo"
        sin_verbo = re.sub(r"\s+", " ", _LIMPIA_PERSONA.sub("", concepto)).strip()
        persona = re.sub(r"^(?:a|de|en|con)\s+", "", sin_verbo, flags=re.IGNORECASE).strip() or "Sin nombre"
        return Movimiento(tipo, concepto or "Sin concepto", centimos, "Deudas", fecha, persona)

    concepto = concepto or "Sin concepto"
    tipo = "ingreso" if es_ingreso_por_signo or _RE_INGRESO.search(normalizado) else "gasto"
    categoria, dudosa = clasificar(tipo, concepto, aprendida)
    return Movimiento(tipo, concepto, centimos, categoria, fecha, dudosa=dudosa)


def parsear(texto: str, hoy: date | None = None, aprendida=None) -> Movimiento:
    return _parsear_pieza(texto, hoy or tiempo.hoy(), aprendida)


def _dividir(texto: str) -> list[str]:
    partes = []
    for bloque in re.split(r"[;\n]|,\s+", texto):
        bloque = bloque.strip()
        if not bloque:
            continue
        sub = re.split(r"\s+y\s+", bloque, flags=re.IGNORECASE)
        if len(sub) > 1 and all(re.search(r"\d", s) for s in sub):
            partes.extend(s.strip() for s in sub)
        else:
            partes.append(bloque)
    return partes


def parsear_varios(texto: str, hoy: date | None = None, aprendida=None) -> list[Movimiento]:
    """Varios movimientos en una línea: 'menú 12, taxi 8' o 'ayer menú 12 y taxi 8'."""
    hoy = hoy or tiempo.hoy()
    partes = _dividir(texto or "")
    if not partes:
        raise ErrorParser("Escribe algo, por ejemplo: almuerzo 18")
    if len(partes) > MAX_PIEZAS:
        raise ErrorParser(f"Máximo {MAX_PIEZAS} movimientos por línea.")
    movimientos = [_parsear_pieza(p, hoy, aprendida) for p in partes]
    fecha_comun = next((m.fecha for m in movimientos if m.fecha), None)
    for m in movimientos:
        if m.fecha is None:
            m.fecha = fecha_comun
    return movimientos
