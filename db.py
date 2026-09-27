import calendar
import os
import re
from contextlib import closing
from datetime import timedelta

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

import tiempo
from parseo import CATEGORIAS_BASE, CATEGORIAS_INGRESO_BASE, SIN_CLASIFICAR, normalizar

ESQUEMA = """
CREATE TABLE IF NOT EXISTS gastos (
    id SERIAL PRIMARY KEY,
    fecha TEXT NOT NULL,
    texto TEXT NOT NULL,
    concepto TEXT NOT NULL,
    monto_centimos INTEGER NOT NULL CHECK (monto_centimos > 0),
    categoria TEXT NOT NULL,
    categoria_auto TEXT NOT NULL,
    creado TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gastos_fecha ON gastos (fecha);

CREATE TABLE IF NOT EXISTS ingresos (
    id SERIAL PRIMARY KEY,
    fecha TEXT NOT NULL,
    texto TEXT NOT NULL,
    concepto TEXT NOT NULL,
    monto_centimos INTEGER NOT NULL CHECK (monto_centimos > 0),
    categoria TEXT NOT NULL,
    categoria_auto TEXT NOT NULL,
    creado TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ingresos_fecha ON ingresos (fecha);

CREATE TABLE IF NOT EXISTS topes (
    categoria TEXT PRIMARY KEY,
    monto_centimos INTEGER NOT NULL CHECK (monto_centimos > 0)
);

CREATE TABLE IF NOT EXISTS fijos (
    id SERIAL PRIMARY KEY,
    concepto TEXT NOT NULL,
    monto_centimos INTEGER NOT NULL CHECK (monto_centimos > 0),
    categoria TEXT NOT NULL,
    dia INTEGER NOT NULL CHECK (dia BETWEEN 1 AND 31),
    activo INTEGER NOT NULL DEFAULT 1,
    ultimo_mes TEXT
);

CREATE TABLE IF NOT EXISTS deudas (
    id SERIAL PRIMARY KEY,
    persona TEXT NOT NULL,
    monto_centimos INTEGER NOT NULL CHECK (monto_centimos > 0),
    tipo TEXT NOT NULL CHECK (tipo IN ('me_deben', 'debo')),
    nota TEXT NOT NULL DEFAULT '',
    fecha TEXT NOT NULL,
    pagada_fecha TEXT
);

CREATE TABLE IF NOT EXISTS categorias (
    nombre TEXT NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('gasto', 'ingreso')),
    creado TEXT NOT NULL,
    PRIMARY KEY (nombre, tipo)
);

CREATE TABLE IF NOT EXISTS aprendido (
    palabra TEXT NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('gasto', 'ingreso')),
    categoria TEXT NOT NULL,
    actualizado TEXT NOT NULL,
    PRIMARY KEY (palabra, tipo)
);

CREATE TABLE IF NOT EXISTS borrados (
    id SERIAL PRIMARY KEY,
    tipo TEXT NOT NULL CHECK (tipo IN ('gasto', 'ingreso', 'deuda', 'fijo', 'categoria')),
    descripcion TEXT NOT NULL,
    detalle TEXT NOT NULL DEFAULT '',
    monto_centimos INTEGER,
    fecha TEXT,
    borrado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_borrados_fecha ON borrados (borrado_en DESC);
"""

# "Otros" no decía nada: ahora se llama "Sin clasificar" y la app insiste en que lo ordenes.
MIGRACIONES = """
UPDATE gastos SET categoria = 'Sin clasificar' WHERE categoria = 'Otros';
UPDATE gastos SET categoria_auto = 'Sin clasificar' WHERE categoria_auto = 'Otros';
UPDATE ingresos SET categoria = 'Sin clasificar' WHERE categoria IN ('Otros', 'Otros ingresos');
UPDATE ingresos SET categoria_auto = 'Sin clasificar' WHERE categoria_auto IN ('Otros', 'Otros ingresos');
DELETE FROM topes WHERE categoria = 'Otros';
UPDATE fijos SET categoria = 'Sin clasificar' WHERE categoria = 'Otros';
"""

TABLAS = ("gastos", "ingresos")
TIPOS_CATEGORIA = ("gasto", "ingreso")
NOMBRE_CATEGORIA = re.compile(r"[^\W_][\w \-&.,()]{1,29}")
CAMPOS_EDITABLES = ("concepto", "monto_centimos", "fecha", "categoria")
UMBRAL_CERCA = 80

# Esquema de Postgres que usa la app. "public" en producción; las pruebas usan uno
# propio y aislado por corrida (ver tests/test_app.py) para no tocar datos reales.
_esquema = "public"


def configurar(schema: str = "public") -> None:
    global _esquema
    _esquema = schema


def hoy() -> str:
    return tiempo.hoy().strftime("%Y-%m-%d")


def _parametros_conexion() -> dict:
    return dict(
        host=os.environ["PG_HOST"],
        port=int(os.environ.get("PG_PORT", "5432")),
        dbname=os.environ["PG_DATABASE"],
        user=os.environ["PG_USER"],
        password=os.environ["PG_PASSWORD"],
        sslmode=os.environ.get("PG_SSLMODE", "disable"),
    )


_pool = None


def _obtener_pool() -> ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = ThreadedConnectionPool(1, 20, **_parametros_conexion())
    return _pool


class _ConexionDelPool:
    """Se comporta como una conexión de psycopg2 normal, salvo que close() la
    devuelve al pool en vez de cerrarla. Abrir una conexión (viaje de red +
    autenticación) por cada consulta es lo que hacía muy lenta la app contra
    un Postgres remoto — a diferencia de SQLite, donde abrir un archivo es
    prácticamente gratis. El resto de db.py no cambia: sigue usando
    `with closing(conectar()) as con:` igual que antes."""

    def __init__(self, con):
        self._con = con

    def __getattr__(self, nombre):
        return getattr(self._con, nombre)

    def close(self) -> None:
        try:
            self._con.rollback()
        except Exception:
            pass
        _obtener_pool().putconn(self._con)


# Qué esquema tiene fijado cada conexión del pool ahora mismo (no se le pueden
# poner atributos propios al objeto de conexión de psycopg2, por eso aparte).
_esquemas_por_conexion: dict[int, str] = {}


def conectar():
    con = _obtener_pool().getconn()
    con.cursor_factory = RealDictCursor
    # Si esta conexión ya apunta al esquema correcto (el caso normal, con
    # mucha diferencia), nos ahorramos dos viajes de red (SET + COMMIT) en
    # cada préstamo del pool.
    if _esquemas_por_conexion.get(id(con)) != _esquema:
        with con.cursor() as cur:
            cur.execute(f'SET search_path TO "{_esquema}"')
        con.commit()
        _esquemas_por_conexion[id(con)] = _esquema
    return _ConexionDelPool(con)


def iniciar() -> None:
    # Primero, sin forzar el search_path (puede que el esquema todavía no exista).
    with closing(psycopg2.connect(**_parametros_conexion())) as con, con.cursor() as cur:
        cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{_esquema}"')
        con.commit()
    with closing(conectar()) as con, con.cursor() as cur:
        cur.execute(ESQUEMA)
        cur.execute(MIGRACIONES)
        con.commit()


def _tabla(tabla: str) -> str:
    if tabla not in TABLAS:
        raise ValueError("Tabla no válida")
    return tabla


def _fila(r) -> dict:
    return {
        "id": r["id"],
        "fecha": r["fecha"],
        "texto": r["texto"],
        "concepto": r["concepto"],
        "monto_centimos": r["monto_centimos"],
        "categoria": r["categoria"],
        "categoria_auto": r["categoria_auto"],
    }


# ---------- Movimientos (gastos e ingresos) ----------

def _insertar(con, tabla: str, texto: str, concepto: str, monto_centimos: int,
              categoria: str, fecha: str | None, categoria_auto: str | None = None) -> dict:
    tabla = _tabla(tabla)
    with con.cursor() as cur:
        cur.execute(
            f"INSERT INTO {tabla} (fecha, texto, concepto, monto_centimos, categoria, categoria_auto, creado)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *",
            (fecha or hoy(), texto, concepto, monto_centimos, categoria, categoria_auto or categoria,
             tiempo.ahora().isoformat(timespec="microseconds")),
        )
        return _fila(cur.fetchone())


def insertar(tabla: str, texto: str, concepto: str, monto_centimos: int, categoria: str,
             fecha: str | None = None, categoria_auto: str | None = None) -> dict:
    """categoria_auto = lo que adivinó la app; si el usuario eligió otra, se guarda distinta."""
    with closing(conectar()) as con:
        fila = _insertar(con, tabla, texto, concepto, monto_centimos, categoria, fecha, categoria_auto)
        con.commit()
        return fila


def obtener(tabla: str, mov_id: int) -> dict | None:
    with closing(conectar()) as con, con.cursor() as cur:
        cur.execute(f"SELECT * FROM {_tabla(tabla)} WHERE id = %s", (mov_id,))
        fila = cur.fetchone()
        return _fila(fila) if fila else None


def listar(tabla: str, mes: str | None = None, q: str | None = None,
           categoria: str | None = None, limite: int | None = None) -> list[dict]:
    condiciones, params = [], []
    if mes:
        condiciones.append("substr(fecha, 1, 7) = %s")
        params.append(mes)
    if q:
        escapado = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        condiciones.append("concepto LIKE %s ESCAPE '\\'")
        params.append(f"%{escapado}%")
    if categoria:
        condiciones.append("categoria = %s")
        params.append(categoria)
    sql = f"SELECT * FROM {_tabla(tabla)}"
    if condiciones:
        sql += " WHERE " + " AND ".join(condiciones)
    sql += " ORDER BY fecha DESC, id DESC"
    if limite:
        sql += " LIMIT %s"
        params.append(limite)
    with closing(conectar()) as con, con.cursor() as cur:
        cur.execute(sql, params)
        return [_fila(f) for f in cur.fetchall()]


def recientes(limite: int = 30, tabla: str = "gastos") -> list[dict]:
    with closing(conectar()) as con, con.cursor() as cur:
        cur.execute(f"SELECT * FROM {_tabla(tabla)} ORDER BY id DESC LIMIT %s", (limite,))
        return [_fila(f) for f in cur.fetchall()]


def actualizar(tabla: str, mov_id: int, campos: dict) -> dict | None:
    campos = {k: v for k, v in campos.items() if k in CAMPOS_EDITABLES}
    with closing(conectar()) as con, con.cursor() as cur:
        if campos:
            asignaciones = ", ".join(f"{k} = %s" for k in campos)
            cur.execute(
                f"UPDATE {_tabla(tabla)} SET {asignaciones} WHERE id = %s RETURNING *",
                (*campos.values(), mov_id),
            )
            fila = cur.fetchone()
            con.commit()
            return _fila(fila) if fila else None
        cur.execute(f"SELECT * FROM {_tabla(tabla)} WHERE id = %s", (mov_id,))
        fila = cur.fetchone()
        return _fila(fila) if fila else None


def _registrar_borrado(con, tipo: str, descripcion: str, detalle: str = "",
                        monto_centimos: int | None = None, fecha: str | None = None) -> None:
    """Deja constancia en el historial antes de borrar algo. No se puede deshacer desde ahí:
    para eso está el botón 'Deshacer' de cada pantalla; esto es solo para consultar qué pasó."""
    with con.cursor() as cur:
        cur.execute(
            "INSERT INTO borrados (tipo, descripcion, detalle, monto_centimos, fecha, borrado_en)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (tipo, descripcion, detalle, monto_centimos, fecha, tiempo.ahora().isoformat(timespec="microseconds")),
        )


def listar_borrados(limite: int = 200) -> list[dict]:
    with closing(conectar()) as con, con.cursor() as cur:
        cur.execute("SELECT * FROM borrados ORDER BY borrado_en DESC LIMIT %s", (limite,))
        return [dict(f) for f in cur.fetchall()]


def borrar(tabla: str, mov_id: int) -> bool:
    tipo = "gasto" if tabla == "gastos" else "ingreso"
    with closing(conectar()) as con, con.cursor() as cur:
        cur.execute(f"SELECT * FROM {_tabla(tabla)} WHERE id = %s", (mov_id,))
        fila = cur.fetchone()
        if fila is None:
            return False
        _registrar_borrado(con, tipo, fila["concepto"], fila["categoria"], fila["monto_centimos"], fila["fecha"])
        cur.execute(f"DELETE FROM {_tabla(tabla)} WHERE id = %s", (mov_id,))
        borrado = cur.rowcount > 0
        con.commit()
        return borrado


def cambiar_categoria(gasto_id: int, categoria: str) -> dict | None:
    return actualizar("gastos", gasto_id, {"categoria": categoria})


def total(tabla: str, mes: str | None = None, dia: str | None = None) -> tuple[int, int]:
    """(suma en céntimos, cantidad) de un mes (AAAA-MM) o un día (AAAA-MM-DD)."""
    if dia:
        cond, param = "fecha = %s", dia
    else:
        cond, param = "substr(fecha, 1, 7) = %s", mes
    with closing(conectar()) as con, con.cursor() as cur:
        cur.execute(
            f"SELECT COALESCE(SUM(monto_centimos), 0) AS s, COUNT(*) AS n FROM {_tabla(tabla)} WHERE {cond}",
            (param,),
        )
        fila = cur.fetchone()
        return fila["s"], fila["n"]


def resumen_movimientos(tabla: str, mes: str) -> dict:
    """Tarjeta de cabecera de Movimientos: total, cantidad, mayor categoría y mes anterior."""
    anio, num = int(mes[:4]), int(mes[5:7])
    anterior = _mes_anterior(anio, num)
    with closing(conectar()) as con, con.cursor() as cur:
        cur.execute(
            f"SELECT categoria, SUM(monto_centimos) AS t FROM {_tabla(tabla)}"
            " WHERE substr(fecha, 1, 7) = %s GROUP BY categoria ORDER BY t DESC LIMIT 1",
            (mes,),
        )
        mayor = cur.fetchone()
    suma, cantidad = total(tabla, mes=mes)
    return {
        "mes": mes,
        "total_centimos": suma,
        "n": cantidad,
        "mayor_categoria": mayor["categoria"] if mayor else None,
        "mes_anterior": anterior,
        "total_mes_anterior_centimos": total(tabla, mes=anterior)[0],
    }


def frecuentes(limite: int = 6, dias: int = 60) -> list[dict]:
    desde = (tiempo.hoy() - timedelta(days=dias)).strftime("%Y-%m-%d")
    with closing(conectar()) as con, con.cursor() as cur:
        cur.execute(
            "SELECT MAX(concepto) AS concepto, monto_centimos, MAX(categoria) AS categoria,"
            " COUNT(*) AS veces, MAX(id) AS ultimo FROM gastos"
            " WHERE fecha >= %s AND texto NOT LIKE 'Gasto fijo:%%'"
            " GROUP BY lower(concepto), monto_centimos HAVING COUNT(*) >= 2"
            " ORDER BY veces DESC, ultimo DESC LIMIT %s",
            (desde, limite),
        )
        filas = cur.fetchall()
        return [
            {"concepto": f["concepto"], "monto_centimos": f["monto_centimos"],
             "categoria": f["categoria"], "veces": f["veces"]}
            for f in filas
        ]


def todos_los_movimientos() -> list[dict]:
    with closing(conectar()) as con, con.cursor() as cur:
        cur.execute(
            "SELECT 'gasto' AS tipo, fecha, concepto, categoria, monto_centimos, texto FROM gastos"
            " UNION ALL "
            "SELECT 'ingreso', fecha, concepto, categoria, monto_centimos, texto FROM ingresos"
            " ORDER BY fecha DESC, tipo"
        )
        return [dict(f) for f in cur.fetchall()]


# ---------- Resumen del mes ----------

def _mes_anterior(anio: int, mes: int) -> str:
    return f"{anio - 1}-12" if mes == 1 else f"{anio}-{mes - 1:02d}"


def _dias_transcurridos(anio: int, mes: int) -> int:
    """Días del mes ya vividos: todos si es pasado, hasta hoy si es el actual, 0 si es futuro."""
    ahora = tiempo.ahora()
    if (anio, mes) == (ahora.year, ahora.month):
        return ahora.day
    if (anio, mes) < (ahora.year, ahora.month):
        return calendar.monthrange(anio, mes)[1]
    return 0


def resumen_mes(mes: str) -> dict:
    """mes con formato YYYY-MM."""
    anio, num_mes = int(mes[:4]), int(mes[5:7])
    transcurridos = _dias_transcurridos(anio, num_mes)
    anterior = _mes_anterior(anio, num_mes)

    with closing(conectar()) as con, con.cursor() as cur:
        cur.execute(
            "SELECT categoria, SUM(monto_centimos) AS total, COUNT(*) AS n FROM gastos"
            " WHERE substr(fecha, 1, 7) = %s GROUP BY categoria ORDER BY total DESC",
            (mes,),
        )
        por_categoria = cur.fetchall()
        cur.execute(
            "SELECT CAST(substr(fecha, 9, 2) AS INTEGER) AS dia, SUM(monto_centimos) AS total FROM gastos"
            " WHERE substr(fecha, 1, 7) = %s GROUP BY dia",
            (mes,),
        )
        por_dia_filas = cur.fetchall()
        cur.execute(
            "SELECT * FROM gastos WHERE substr(fecha, 1, 7) = %s ORDER BY fecha DESC, id DESC LIMIT 6", (mes,)
        )
        ultimos = cur.fetchall()

    total_gastos = sum(f["total"] for f in por_categoria)
    categorias_resumen = [
        {
            "categoria": f["categoria"],
            "total_centimos": f["total"],
            "n": f["n"],
            "porcentaje": round(100 * f["total"] / total_gastos, 1) if total_gastos else 0,
        }
        for f in por_categoria
    ]

    dias_mes = calendar.monthrange(anio, num_mes)[1]
    totales_por_dia = {f["dia"]: f["total"] for f in por_dia_filas}
    por_dia = [totales_por_dia.get(d, 0) for d in range(1, dias_mes + 1)]
    dia_mayor = None
    if totales_por_dia:
        d = max(totales_por_dia, key=lambda k: (totales_por_dia[k], -k))
        dia_mayor = {"dia": d, "total_centimos": totales_por_dia[d]}

    return {
        "mes": mes,
        "total_centimos": total_gastos,
        "n_gastos": sum(f["n"] for f in por_categoria),
        "ingresos_centimos": total("ingresos", mes=mes)[0],
        "dias_con_registro": len(totales_por_dia),
        "dias_transcurridos": transcurridos,
        "promedio_diario_centimos": round(total_gastos / transcurridos) if transcurridos else 0,
        "por_dia_centimos": por_dia,
        "dia_mayor": dia_mayor,
        "mes_anterior": anterior,
        "total_mes_anterior_centimos": total("gastos", mes=anterior)[0],
        "categoria_top": categorias_resumen[0]["categoria"] if categorias_resumen else None,
        "categorias": categorias_resumen,
        "ultimos": [_fila(f) for f in ultimos],
    }


# ---------- Categorías: de fábrica + las del usuario ----------

class ErrorCategoria(ValueError):
    """Petición de categoría inválida (se responde con 400/409)."""


def _tipo_categoria(tipo: str) -> str:
    if tipo not in TIPOS_CATEGORIA:
        raise ErrorCategoria("Tipo de categoría no válido.")
    return tipo


def _tabla_de(tipo: str) -> str:
    return "gastos" if tipo == "gasto" else "ingresos"


def propias(tipo: str) -> list[str]:
    with closing(conectar()) as con, con.cursor() as cur:
        cur.execute("SELECT nombre FROM categorias WHERE tipo = %s ORDER BY creado, nombre", (tipo,))
        return [f["nombre"] for f in cur.fetchall()]


def categorias(tipo: str = "gasto") -> list[str]:
    """De fábrica y propias, con 'Sin clasificar' siempre al final."""
    base = CATEGORIAS_BASE if tipo == "gasto" else CATEGORIAS_INGRESO_BASE
    return [c for c in base if c != SIN_CLASIFICAR] + propias(tipo) + [SIN_CLASIFICAR]


def _uso(con, tipo: str, nombre: str) -> int:
    with con.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS n FROM {_tabla_de(tipo)} WHERE categoria = %s", (nombre,))
        n = cur.fetchone()["n"]
        if tipo == "gasto":
            cur.execute("SELECT COUNT(*) AS n FROM fijos WHERE categoria = %s", (nombre,))
            n += cur.fetchone()["n"]
        return n


def listar_categorias(tipo: str = "gasto") -> list[dict]:
    mias = set(propias(tipo))
    with closing(conectar()) as con:
        return [{"nombre": c, "propia": c in mias, "en_uso": _uso(con, tipo, c)} for c in categorias(tipo)]


def limpiar_nombre_categoria(nombre) -> str:
    nombre = re.sub(r"\s+", " ", str(nombre or "")).strip()
    if not NOMBRE_CATEGORIA.fullmatch(nombre):
        raise ErrorCategoria("El nombre debe tener de 2 a 30 caracteres: letras, números, espacios y - & . , ( )")
    return nombre


def _ya_existe(tipo: str, nombre: str, ignorar: str | None = None) -> bool:
    buscado = normalizar(nombre)
    return any(normalizar(c) == buscado and c != ignorar for c in categorias(tipo))


def crear_categoria(tipo: str, nombre: str) -> dict:
    tipo = _tipo_categoria(tipo)
    nombre = limpiar_nombre_categoria(nombre)
    if _ya_existe(tipo, nombre):
        raise ErrorCategoria("Ya existe una categoría con ese nombre.")
    with closing(conectar()) as con, con.cursor() as cur:
        cur.execute(
            "INSERT INTO categorias (nombre, tipo, creado) VALUES (%s, %s, %s)",
            (nombre, tipo, tiempo.ahora().isoformat(timespec="microseconds")),
        )
        con.commit()
    return {"nombre": nombre, "tipo": tipo, "propia": True, "en_uso": 0}


def renombrar_categoria(tipo: str, actual: str, nuevo: str) -> dict:
    tipo = _tipo_categoria(tipo)
    nuevo = limpiar_nombre_categoria(nuevo)
    if actual not in propias(tipo):
        raise ErrorCategoria("Solo puedes renombrar las categorías que tú creaste.")
    if _ya_existe(tipo, nuevo, ignorar=actual):
        raise ErrorCategoria("Ya existe una categoría con ese nombre.")
    tabla = _tabla_de(tipo)
    with closing(conectar()) as con, con.cursor() as cur:
        cur.execute("UPDATE categorias SET nombre = %s WHERE nombre = %s AND tipo = %s", (nuevo, actual, tipo))
        cur.execute(f"UPDATE {tabla} SET categoria = %s WHERE categoria = %s", (nuevo, actual))
        cur.execute(f"UPDATE {tabla} SET categoria_auto = %s WHERE categoria_auto = %s", (nuevo, actual))
        cur.execute("UPDATE aprendido SET categoria = %s WHERE categoria = %s AND tipo = %s", (nuevo, actual, tipo))
        if tipo == "gasto":
            cur.execute("UPDATE topes SET categoria = %s WHERE categoria = %s", (nuevo, actual))
            cur.execute("UPDATE fijos SET categoria = %s WHERE categoria = %s", (nuevo, actual))
        con.commit()
        return {"nombre": nuevo, "tipo": tipo, "propia": True, "en_uso": _uso(con, tipo, nuevo)}


def borrar_categoria(tipo: str, nombre: str) -> None:
    tipo = _tipo_categoria(tipo)
    if nombre not in propias(tipo):
        raise ErrorCategoria("Solo puedes borrar las categorías que tú creaste.")
    with closing(conectar()) as con:
        n = _uso(con, tipo, nombre)
        if n:
            raise ErrorCategoria(
                f"Todavía tiene {n} {'movimiento' if n == 1 else 'movimientos'}. "
                "Pásalos a otra categoría antes de borrarla, o cámbiale el nombre."
            )
        with con.cursor() as cur:
            _registrar_borrado(con, "categoria", nombre, "Categoría de " + tipo)
            cur.execute("DELETE FROM categorias WHERE nombre = %s AND tipo = %s", (nombre, tipo))
            cur.execute("DELETE FROM aprendido WHERE categoria = %s AND tipo = %s", (nombre, tipo))
            if tipo == "gasto":
                cur.execute("DELETE FROM topes WHERE categoria = %s", (nombre,))
        con.commit()


def aprender(tipo: str, tokens: list[str], categoria: str) -> None:
    """Recuerda que estas palabras van en esta categoría (lo elegido por el usuario manda)."""
    if not tokens or len(tokens) > 3 or categoria == SIN_CLASIFICAR:
        return
    ahora = tiempo.ahora().isoformat(timespec="microseconds")
    with closing(conectar()) as con, con.cursor() as cur:
        for palabra in tokens:
            cur.execute(
                "INSERT INTO aprendido (palabra, tipo, categoria, actualizado) VALUES (%s, %s, %s, %s)"
                " ON CONFLICT (palabra, tipo) DO UPDATE SET categoria = EXCLUDED.categoria,"
                " actualizado = EXCLUDED.actualizado",
                (palabra, tipo, categoria, ahora),
            )
        con.commit()


def categoria_aprendida(tipo: str, tokens: list[str]) -> str | None:
    if not tokens:
        return None
    marcas = ",".join(["%s"] * len(tokens))
    with closing(conectar()) as con, con.cursor() as cur:
        cur.execute(
            f"SELECT categoria FROM aprendido WHERE tipo = %s AND palabra IN ({marcas})"
            " ORDER BY actualizado DESC LIMIT 1",
            (tipo, *tokens),
        )
        fila = cur.fetchone()
        return fila["categoria"] if fila else None


CATEGORIAS_POR_DEFECTO = {
    "gasto": ["Comida", "Transporte", "Mercado", "Servicios", "Salud", "Ocio"],
    "ingreso": ["Sueldo", "Ventas y cachuelos", "Regalos y apoyo", "Cobro de deudas"],
}


def categorias_mas_usadas(tipo: str = "gasto", limite: int = 6, dias: int = 90) -> list[str]:
    """Las que más usa la persona (últimos meses); si aún usa pocas, se completa con las de siempre."""
    tipo = _tipo_categoria(tipo)
    desde = (tiempo.hoy() - timedelta(days=dias)).strftime("%Y-%m-%d")
    with closing(conectar()) as con, con.cursor() as cur:
        cur.execute(
            f"SELECT categoria FROM {_tabla_de(tipo)} WHERE fecha >= %s AND categoria != %s"
            " GROUP BY categoria ORDER BY COUNT(*) DESC, MAX(id) DESC LIMIT %s",
            (desde, SIN_CLASIFICAR, limite),
        )
        filas = cur.fetchall()
    validas = set(categorias(tipo))
    resultado = [f["categoria"] for f in filas if f["categoria"] in validas]
    for c in CATEGORIAS_POR_DEFECTO[tipo]:
        if len(resultado) >= limite:
            break
        if c not in resultado and c in validas:
            resultado.append(c)
    return resultado


def anotados_hoy(limite: int = 30) -> list[dict]:
    """Lo que se anotó hoy (aunque sea de otro día), para confirmar que quedó guardado."""
    hoy_ = hoy()
    with closing(conectar()) as con, con.cursor() as cur:
        cur.execute(
            "SELECT 'gasto' AS tipo, id, fecha, concepto, categoria, monto_centimos, creado FROM gastos"
            " WHERE substr(creado, 1, 10) = %s AND texto NOT LIKE 'Gasto fijo:%%'"
            " UNION ALL "
            "SELECT 'ingreso', id, fecha, concepto, categoria, monto_centimos, creado FROM ingresos"
            " WHERE substr(creado, 1, 10) = %s"
            " ORDER BY creado DESC LIMIT %s",
            (hoy_, hoy_, limite),
        )
        filas = cur.fetchall()
    return [{k: f[k] for k in ("tipo", "id", "fecha", "concepto", "categoria", "monto_centimos")} for f in filas]


def sin_clasificar(mes: str) -> dict:
    with closing(conectar()) as con, con.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(monto_centimos), 0) AS t FROM gastos"
            " WHERE categoria = %s AND substr(fecha, 1, 7) = %s",
            (SIN_CLASIFICAR, mes),
        )
        fila = cur.fetchone()
    return {"n": fila["n"], "total_centimos": fila["t"]}


# ---------- Topes por categoría ----------

def guardar_tope(categoria: str, monto_centimos: int) -> None:
    with closing(conectar()) as con, con.cursor() as cur:
        cur.execute(
            "INSERT INTO topes (categoria, monto_centimos) VALUES (%s, %s)"
            " ON CONFLICT (categoria) DO UPDATE SET monto_centimos = EXCLUDED.monto_centimos",
            (categoria, monto_centimos),
        )
        con.commit()


def borrar_tope(categoria: str) -> bool:
    with closing(conectar()) as con, con.cursor() as cur:
        cur.execute("DELETE FROM topes WHERE categoria = %s", (categoria,))
        borrado = cur.rowcount > 0
        con.commit()
        return borrado


def estado_topes(mes: str, lista: list[str] | None = None) -> list[dict]:
    """Una fila por categoría, con su tope (si existe) y lo gastado en el mes."""
    if lista is None:
        lista = [c for c in categorias("gasto") if c != SIN_CLASIFICAR]
    with closing(conectar()) as con, con.cursor() as cur:
        cur.execute("SELECT * FROM topes")
        topes = {f["categoria"]: f["monto_centimos"] for f in cur.fetchall()}
        cur.execute(
            "SELECT categoria, SUM(monto_centimos) AS t FROM gastos WHERE substr(fecha, 1, 7) = %s"
            " GROUP BY categoria",
            (mes,),
        )
        gastado = {f["categoria"]: f["t"] for f in cur.fetchall()}
    filas = []
    for categoria in lista:
        tope = topes.get(categoria)
        usado = gastado.get(categoria, 0)
        fila = {"categoria": categoria, "tope_centimos": tope, "gastado_centimos": usado,
                "porcentaje": None, "estado": None, "restante_centimos": None}
        if tope:
            pct = round(100 * usado / tope)
            fila.update(
                porcentaje=pct,
                estado="pasado" if usado >= tope else "cerca" if pct >= UMBRAL_CERCA else "ok",
                restante_centimos=tope - usado,
            )
        filas.append(fila)
    return filas


# ---------- Gastos fijos ----------

def _fijo(r) -> dict:
    return {"id": r["id"], "concepto": r["concepto"], "monto_centimos": r["monto_centimos"],
            "categoria": r["categoria"], "dia": r["dia"], "activo": bool(r["activo"]),
            "ultimo_mes": r["ultimo_mes"]}


def _dia_efectivo(dia: int, anio: int, mes: int) -> int:
    return min(dia, calendar.monthrange(anio, mes)[1])


def listar_fijos() -> list[dict]:
    with closing(conectar()) as con, con.cursor() as cur:
        cur.execute("SELECT * FROM fijos ORDER BY dia, id")
        return [_fijo(f) for f in cur.fetchall()]


def crear_fijo(concepto: str, monto_centimos: int, categoria: str, dia: int) -> dict:
    hoy_ = tiempo.hoy()
    # Si su día ya pasó este mes, arranca desde el próximo: no se inventan gastos del pasado.
    ya_paso = _dia_efectivo(dia, hoy_.year, hoy_.month) <= hoy_.day
    ultimo_mes = hoy_.strftime("%Y-%m") if ya_paso else None
    with closing(conectar()) as con, con.cursor() as cur:
        cur.execute(
            "INSERT INTO fijos (concepto, monto_centimos, categoria, dia, activo, ultimo_mes)"
            " VALUES (%s, %s, %s, %s, 1, %s) RETURNING *",
            (concepto, monto_centimos, categoria, dia, ultimo_mes),
        )
        fila = cur.fetchone()
        con.commit()
        return _fijo(fila)


def actualizar_fijo(fijo_id: int, campos: dict) -> dict | None:
    permitidos = {"concepto", "monto_centimos", "categoria", "dia", "activo"}
    campos = {k: (int(v) if k == "activo" else v) for k, v in campos.items() if k in permitidos}
    with closing(conectar()) as con, con.cursor() as cur:
        if campos:
            asignaciones = ", ".join(f"{k} = %s" for k in campos)
            cur.execute(f"UPDATE fijos SET {asignaciones} WHERE id = %s RETURNING *", (*campos.values(), fijo_id))
            fila = cur.fetchone()
            con.commit()
            return _fijo(fila) if fila else None
        cur.execute("SELECT * FROM fijos WHERE id = %s", (fijo_id,))
        fila = cur.fetchone()
        return _fijo(fila) if fila else None


def borrar_fijo(fijo_id: int) -> bool:
    with closing(conectar()) as con, con.cursor() as cur:
        cur.execute("SELECT * FROM fijos WHERE id = %s", (fijo_id,))
        fila = cur.fetchone()
        if fila is None:
            return False
        _registrar_borrado(con, "fijo", fila["concepto"], fila["categoria"], fila["monto_centimos"])
        cur.execute("DELETE FROM fijos WHERE id = %s", (fijo_id,))
        borrado = cur.rowcount > 0
        con.commit()
        return borrado


def generar_fijos() -> int:
    """Registra los gastos fijos del mes actual cuyo día ya llegó. Devuelve cuántos creó."""
    hoy_ = tiempo.hoy()
    mes = hoy_.strftime("%Y-%m")
    with closing(conectar()) as lectura, lectura.cursor() as cur:
        cur.execute(
            "SELECT dia FROM fijos WHERE activo = 1 AND (ultimo_mes IS NULL OR ultimo_mes != %s)", (mes,)
        )
        candidatos = cur.fetchall()
    if not any(_dia_efectivo(f["dia"], hoy_.year, hoy_.month) <= hoy_.day for f in candidatos):
        return 0

    creados = 0
    con = conectar()
    try:
        with con.cursor() as cur:
            cur.execute(
                "SELECT * FROM fijos WHERE activo = 1 AND (ultimo_mes IS NULL OR ultimo_mes != %s) FOR UPDATE",
                (mes,),
            )
            pendientes = cur.fetchall()
            for f in pendientes:
                dia = _dia_efectivo(f["dia"], hoy_.year, hoy_.month)
                if dia > hoy_.day:
                    continue
                fecha = f"{mes}-{dia:02d}"
                _insertar(con, "gastos", f"Gasto fijo: {f['concepto']}", f["concepto"], f["monto_centimos"],
                          f["categoria"], fecha)
                cur.execute("UPDATE fijos SET ultimo_mes = %s WHERE id = %s", (mes, f["id"]))
                creados += 1
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return creados


def proximos_fijos(dias: int = 7) -> list[dict]:
    """Fijos activos que faltan por vencer este mes, dentro de los próximos `dias`."""
    hoy_ = tiempo.hoy()
    resultado = []
    for f in listar_fijos():
        if not f["activo"]:
            continue
        dia = _dia_efectivo(f["dia"], hoy_.year, hoy_.month)
        if hoy_.day < dia <= hoy_.day + dias:
            resultado.append({**f, "dia": dia, "faltan_dias": dia - hoy_.day})
    return resultado


# ---------- Deudas ----------

def _deuda(r) -> dict:
    return {"id": r["id"], "persona": r["persona"], "monto_centimos": r["monto_centimos"],
            "tipo": r["tipo"], "nota": r["nota"], "fecha": r["fecha"], "pagada_fecha": r["pagada_fecha"]}


def crear_deuda(persona: str, monto_centimos: int, tipo: str, nota: str = "",
                fecha: str | None = None) -> dict:
    """Si me deben, el dinero ya salió de mi bolsillo: se anota también como gasto en 'Deudas'."""
    with closing(conectar()) as con, con.cursor() as cur:
        cur.execute(
            "INSERT INTO deudas (persona, monto_centimos, tipo, nota, fecha) VALUES (%s, %s, %s, %s, %s)"
            " RETURNING *",
            (persona, monto_centimos, tipo, nota, fecha or hoy()),
        )
        fila = cur.fetchone()
        gasto = None
        if tipo == "me_deben":
            gasto = _insertar(con, "gastos", f"Préstamo a {persona}", f"Préstamo a {persona}",
                              monto_centimos, "Deudas", fecha)
        con.commit()
        deuda = _deuda(fila)
        deuda["gasto"] = gasto
        return deuda


def listar_deudas(incluir_pagadas: bool = False) -> list[dict]:
    sql = "SELECT * FROM deudas"
    if not incluir_pagadas:
        sql += " WHERE pagada_fecha IS NULL"
    sql += " ORDER BY pagada_fecha IS NOT NULL, fecha DESC, id DESC"
    with closing(conectar()) as con, con.cursor() as cur:
        cur.execute(sql)
        return [_deuda(f) for f in cur.fetchall()]


def pagar_deuda(deuda_id: int) -> dict | None:
    """Marca la deuda como pagada y mueve el dinero: cobro (ingreso) o pago (gasto)."""
    with closing(conectar()) as con, con.cursor() as cur:
        cur.execute("SELECT * FROM deudas WHERE id = %s", (deuda_id,))
        fila = cur.fetchone()
        if fila is None:
            return None
        if fila["pagada_fecha"]:
            raise ValueError("Esa deuda ya está pagada.")
        if fila["tipo"] == "me_deben":
            mov = _insertar(con, "ingresos", f"Cobro a {fila['persona']}", f"Cobro a {fila['persona']}",
                            fila["monto_centimos"], "Cobro de deudas", None)
            tipo_mov = "ingreso"
        else:
            mov = _insertar(con, "gastos", f"Pago a {fila['persona']}", f"Pago a {fila['persona']}",
                            fila["monto_centimos"], "Deudas", None)
            tipo_mov = "gasto"
        cur.execute("UPDATE deudas SET pagada_fecha = %s WHERE id = %s RETURNING *", (hoy(), deuda_id))
        actualizada = cur.fetchone()
        con.commit()
        deuda = _deuda(actualizada)
        deuda["movimiento"] = {"tipo": tipo_mov, **mov}
        return deuda


def borrar_deuda(deuda_id: int) -> bool:
    with closing(conectar()) as con, con.cursor() as cur:
        cur.execute("SELECT * FROM deudas WHERE id = %s", (deuda_id,))
        fila = cur.fetchone()
        if fila is None:
            return False
        detalle = "Te debía" if fila["tipo"] == "me_deben" else "Le debías"
        if fila["pagada_fecha"]:
            detalle += " · ya estaba pagada"
        _registrar_borrado(con, "deuda", fila["persona"], detalle, fila["monto_centimos"], fila["fecha"])
        cur.execute("DELETE FROM deudas WHERE id = %s", (deuda_id,))
        borrado = cur.rowcount > 0
        con.commit()
        return borrado


def resumen_deudas() -> dict:
    with closing(conectar()) as con, con.cursor() as cur:
        cur.execute(
            "SELECT tipo, SUM(monto_centimos) AS t, COUNT(*) AS n FROM deudas"
            " WHERE pagada_fecha IS NULL GROUP BY tipo"
        )
        filas = {f["tipo"]: (f["t"], f["n"]) for f in cur.fetchall()}
    me_deben = filas.get("me_deben", (0, 0))
    debo = filas.get("debo", (0, 0))
    return {"me_deben_centimos": me_deben[0], "n_me_deben": me_deben[1],
            "debo_centimos": debo[0], "n_debo": debo[1]}


# ---------- Inicio ----------

def ultimos_movimientos(limite: int = 5) -> list[dict]:
    with closing(conectar()) as con, con.cursor() as cur:
        cur.execute(
            "SELECT 'gasto' AS tipo, id, fecha, concepto, categoria, monto_centimos, creado FROM gastos"
            " UNION ALL "
            "SELECT 'ingreso', id, fecha, concepto, categoria, monto_centimos, creado FROM ingresos"
            " ORDER BY creado DESC, id DESC LIMIT %s",
            (limite,),
        )
        filas = cur.fetchall()
        return [{k: f[k] for k in ("tipo", "id", "fecha", "concepto", "categoria", "monto_centimos")} for f in filas]


def inicio() -> dict:
    generar_fijos()
    hoy_ = tiempo.hoy()
    mes = hoy_.strftime("%Y-%m")
    dias_mes = calendar.monthrange(hoy_.year, hoy_.month)[1]
    restantes = dias_mes - hoy_.day + 1  # cuenta hoy

    gastado_mes, _ = total("gastos", mes=mes)
    ingresado_mes, _ = total("ingresos", mes=mes)
    gasto_hoy, n_hoy = total("gastos", dia=hoy())
    disponible = ingresado_mes - gastado_mes
    topes = [t for t in estado_topes(mes) if t["tope_centimos"]]

    return {
        "mes": mes,
        "dias_restantes": restantes,
        "gastado_mes_centimos": gastado_mes,
        "ingresado_mes_centimos": ingresado_mes,
        "disponible_centimos": disponible,
        "por_dia_centimos": disponible // restantes if disponible > 0 else 0,
        "gasto_hoy_centimos": gasto_hoy,
        "n_hoy": n_hoy,
        "sin_registro_hoy": n_hoy == 0,
        "alertas": [t for t in topes if t["estado"] in ("cerca", "pasado")],
        "hay_topes": bool(topes),
        "sin_clasificar": sin_clasificar(mes),
        "proximos_fijos": proximos_fijos(),
        "frecuentes": frecuentes(),
        "deudas": resumen_deudas(),
        "ultimos": ultimos_movimientos(),
        "anotados_hoy": anotados_hoy(),
        "mas_usadas": {"gasto": categorias_mas_usadas("gasto"), "ingreso": categorias_mas_usadas("ingreso")},
    }
