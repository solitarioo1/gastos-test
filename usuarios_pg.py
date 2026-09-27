"""Login real contra la tabla `usuarios` en Postgres (VPS del usuario).

Las claves nunca se guardan ni se comparan en texto plano: se usa el hash
scrypt de werkzeug (generate_password_hash / check_password_hash).
"""
import os

import psycopg2
from werkzeug.security import check_password_hash, generate_password_hash

import tiempo


def _conectar():
    return psycopg2.connect(
        host=os.environ["PG_HOST"],
        port=int(os.environ.get("PG_PORT", "5432")),
        dbname=os.environ["PG_DATABASE"],
        user=os.environ["PG_USER"],
        password=os.environ["PG_PASSWORD"],
        sslmode=os.environ.get("PG_SSLMODE", "disable"),
        connect_timeout=5,
    )


def verificar(usuario: str, clave: str) -> bool:
    """True si el usuario existe y la clave coincide con su hash.

    Cualquier problema de conexión con la base se trata como "no autorizado"
    (nunca se deja pasar a alguien porque la base esté caída).
    """
    usuario = (usuario or "").strip()
    if not usuario or not clave:
        return False
    try:
        with _conectar() as con, con.cursor() as cur:
            cur.execute("SELECT clave_hash FROM usuarios WHERE usuario = %s", (usuario,))
            fila = cur.fetchone()
            if fila is None or not check_password_hash(fila[0], clave):
                return False
            cur.execute(
                "UPDATE usuarios SET ultimo_acceso = %s WHERE usuario = %s",
                (tiempo.ahora().isoformat(timespec="microseconds"), usuario),
            )
            con.commit()
            return True
    except psycopg2.OperationalError:
        return False


def crear_usuario(usuario: str, clave: str) -> None:
    """Crea o actualiza la clave de un usuario. Uso manual (script/consola), no expuesto en la web."""
    usuario = (usuario or "").strip()
    if not usuario or not clave:
        raise ValueError("Usuario y clave son obligatorios.")
    hash_ = generate_password_hash(clave)
    with _conectar() as con, con.cursor() as cur:
        cur.execute(
            "INSERT INTO usuarios (usuario, clave_hash, creado) VALUES (%s, %s, %s)"
            " ON CONFLICT (usuario) DO UPDATE SET clave_hash = EXCLUDED.clave_hash",
            (usuario, hash_, tiempo.ahora().isoformat(timespec="microseconds")),
        )
        con.commit()
