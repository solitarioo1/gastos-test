-- Esquema de TusGastos para Postgres. Es el mismo que usa db.py en SQLite,
-- traducido: AUTOINCREMENT -> SERIAL, el resto es prácticamente igual.
-- La tabla `usuarios` ya la usa la app en vivo (login real, ver usuarios_pg.py).
-- El resto de tablas quedan listas aquí para cuando se haga la migración completa,
-- pero db.py todavía lee/escribe gastos, ingresos, etc. en SQLite.

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

-- Usuarios para el login (usuario + clave). La clave NUNCA se guarda en texto plano:
-- clave_hash es el resultado de werkzeug.security.generate_password_hash (scrypt,
-- con sal aleatoria distinta en cada fila). Verificar con check_password_hash.
CREATE TABLE IF NOT EXISTS usuarios (
    id SERIAL PRIMARY KEY,
    usuario TEXT NOT NULL UNIQUE,
    clave_hash TEXT NOT NULL,
    creado TEXT NOT NULL,
    ultimo_acceso TEXT
);
