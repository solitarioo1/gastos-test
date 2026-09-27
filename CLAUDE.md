# TusGastos

App web de control de gastos personales. Uso personal por ahora (ver `plan.md`
para el contexto de producto/negocio: nombre, decisiones, pagos, competencia).
Multiusuario queda para después — no diseñar pensando en eso todavía.

Usuario objetivo: alguien de pocos recursos que anota rápido. Todo debe figurar
y ser fácil de recordar. El registro de un gasto debe tomar 3 toques: monto,
fecha, categoría. Sin categoría genérica "Otros" — existe "Sin clasificar" +
categorías propias del usuario + aprendizaje automático de palabras.

## Stack y arquitectura

- Flask (app factory `create_app()` en `app.py`), Jinja2, sin frontend framework.
- UI basada en Tabler (MIT) con paleta propia neutra (grafito/blanco como
  primario; verde solo para éxito/positivo; azul para enlaces/información;
  rojo/naranja para advertencias). Ver `static/style.css`.
- Navegación: hamburguesa + cajón deslizable en celular Y tablet (<992px);
  barra lateral fija solo en escritorio real (≥992px).
- **Datos** (gastos, ingresos, topes, fijos, deudas, categorías, aprendizaje,
  historial de borrados): SQLite local, `db.py`, archivo `gastos.db`.
- **Login**: Postgres real en el VPS del usuario (Easypanel), tabla `usuarios`
  con clave hasheada (scrypt, `werkzeug.security`). Módulo `usuarios_pg.py`.
  Es un estado híbrido a propósito: solo el login se migró a Postgres, el
  resto de datos sigue en SQLite. Migrar el resto es trabajo futuro, no
  asumido ni empezado (ver `sql/esquema_postgres.sql`, que ya tiene las
  tablas listas para cuando se decida migrar).

### Cómo entra alguien a la app

No hay pantalla de registro real (el panel "Registrarse" del login es solo
diseño, dice "por ahora, uso personal, por invitación" — no crear cuentas
reales ahí sin que el dueño lo pida explícitamente).

El usuario admin se define por variables de entorno (`PLATA_ADMIN_USER`,
`PLATA_ADMIN_PASSWORD`) y la app las sincroniza contra Postgres **en cada
intento de login** (función `sincronizar_admin()` en `app.py`), no solo al
arrancar. Por eso cambiar esas dos variables en `.env` y volver a intentar
entrar alcanza — no hace falta reiniciar el proceso. Para crear otros
usuarios manualmente (no vía `.env`) está `crear_usuario.py` (pide usuario y
clave por teclado, no los expone en texto).

Conexión a Postgres: **usar la IP directa del VPS** (`PG_HOST`), no el
dominio `panel.intismart.com` — ese dominio pasa por Cloudflare, que bloquea
el puerto de la base (no es HTTP). `sslmode=disable` por ahora; pendiente
activar SSL más adelante.

## Variables de entorno (`.env`, no se versiona)

- `PLATA_ADMIN_USER`, `PLATA_ADMIN_PASSWORD` — credencial de entrada.
- `PLATA_SECRET` — firma de la cookie de sesión.
- `PG_HOST`, `PG_PORT`, `PG_DATABASE`, `PG_USER`, `PG_PASSWORD` — Postgres.
- Opcionales con default: `PLATA_DB` (default `gastos.db`), `PLATA_HTTPS=1`
  (cookies seguras cuando la app corre con HTTPS en el VPS), `PLATA_DEV=1`
  (atajos para correr en local sin toda la config).

## Correr y probar

- Local: `python app.py` (puerto por `PORT`, default 5000).
- Tests: `python -W ignore -m unittest discover -s tests` (154 tests). Las
  pruebas de login NO tocan el Postgres real: `create_app()` acepta
  `AUTENTICAR` como función inyectable, y `tests/test_app.py` usa un stub en
  memoria (ver `BaseApp.setUp` / `BaseApp.entrar`). Si se toca el mecanismo
  de login, mantener ese stub — nunca hacer que los tests dependan de
  internet o del VPS.
- Verificación visual/JS: no hay suite automatizada de UI; este proyecto usó
  Puppeteer + Edge headless desde un script suelto en el scratchpad cuando
  hizo falta comprobar CSS/JS realmente renderizado (no confiar solo en
  inspección visual para bugs de layout/transform).

## Despliegue (Docker + Easypanel, VPS propio)

Subdominio: `registros.intismart.com` (DNS ya configurado). Repo con remoto
GitHub ya enlazado: `solitarioo1/gastos-test` (sin commits todavía al momento
de escribir esto).

- `Dockerfile` + `wsgi.py` (`wsgi:app`, gunicorn) ya están listos. Local sigue
  siendo `python app.py`; el contenedor usa gunicorn, no el server de Flask.
- Las variables de entorno de producción (`PLATA_ADMIN_USER`,
  `PLATA_ADMIN_PASSWORD`, `PLATA_SECRET`, `PLATA_HTTPS=1`, `PG_*`, `PLATA_DB`)
  se configuran **en el panel de Easypanel**, no en `.env` (ese archivo es
  local y está en `.gitignore`, no viaja con la imagen).
- **SQLite necesita volumen persistente**: montar un volumen en Easypanel
  (ej. `/data`) y poner `PLATA_DB=/data/gastos.db` en las variables de esa
  app. Sin esto, `gastos.db` se pierde en cada redeploy porque vive dentro
  del contenedor.
- **Postgres — host interno vs. externo**: `PG_HOST=158.220.124.247` /
  `PG_PORT=5433` es la ruta pública (para conectarse desde fuera del VPS,
  como en desarrollo local). Cuando la app corra COMO CONTENEDOR en el mismo
  proyecto de Easypanel que el servicio de Postgres, debe usar el **host
  interno** de Docker (nombre del servicio dentro de la red interna de
  Easypanel, normalmente puerto 5432) en vez de la IP pública — es más
  rápido y no sale a internet para hablar con su propia base. El nombre
  interno en Easypanel es el **nombre del servicio** tal cual aparece en ese
  proyecto (confirmado con otro proyecto del usuario donde el servicio se
  llama literal `postgres` y `DB_HOST=postgres` funciona). Para esta base,
  **confirmado directamente en el panel de Easypanel** (Credentials de ese
  servicio Postgres): `Internal Host = bd_shp_mapas_gastos-db`,
  `Internal Port = 5432`. En producción usar:
  ```
  PG_HOST=bd_shp_mapas_gastos-db
  PG_PORT=5432
  ```
  Solo funciona si la app de TusGastos está en el **mismo proyecto** de
  Easypanel que ese servicio Postgres (la conexión por nombre interno solo
  funciona dentro del mismo proyecto).
  **No es `localhost`**: aunque la app y Postgres corran en el mismo VPS,
  cada uno vive en su propio contenedor Docker con su propia red —
  `localhost` dentro del contenedor de la app apunta a sí mismo, no al de
  Postgres.

## Cosas ya resueltas, no repetir el error

- Transiciones deslizantes (login): nunca usar `translateX()` en porcentaje
  cuando el elemento y su contenedor también miden en porcentaje — se
  duplica el desplazamiento. Medir en JS y mover en píxeles (ver
  `static/login.js`).
- `display: contents` para "aplanar" un wrapper en un grid/flex requiere que
  el padre real también tenga `display: flex` puesto explícitamente en el
  mismo media query — si no, los paneles se apilan y los clics fallan.
- Borrado de cualquier dato: siempre con diálogo de confirmación, y siempre
  queda registro en la tabla `borrados` (ver `_registrar_borrado` en
  `db.py`), visible en `/historial` (sin opción de restaurar, es solo
  auditoría).
- `/static/*`, `/api/*` y `/login` deben llevar `Cache-Control: no-store`
  (si no, el navegador sirve CSS/JS viejo tras editar).
- Gunicorn en el `Dockerfile` usa `--workers 1 --threads 4` a propósito: el
  bloqueo por intentos fallidos de login (`fallos_login` en `app.py`) vive en
  memoria del proceso; con más de un worker cada proceso llevaría su propio
  conteo y el bloqueo se volvería inconsistente. Si algún día hace falta más
  capacidad, ese conteo tendría que moverse a Postgres/Redis antes de subir
  el número de workers.
