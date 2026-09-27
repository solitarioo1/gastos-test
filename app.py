import csv
import io
import os
import re
import time
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import wraps

from dotenv import load_dotenv
from flask import (Flask, Response, jsonify, redirect, render_template, request, send_from_directory,
                   session, url_for)

import db
import tiempo
import usuarios_pg
from parseo import (MAX_MONTO_CENTIMOS, SIN_CLASIFICAR, ErrorParser, clasificar, parsear_varios,
                    tokens_significativos)

load_dotenv()

APP_NOMBRE = "TusGastos"
MAX_TEXTO = 300
MAX_CONCEPTO = 100
VENTANA_LOGIN_SEG = 300
RE_MES = re.compile(r"\d{4}-(0[1-9]|1[0-2])")
RE_FECHA = re.compile(r"\d{4}-\d{2}-\d{2}")


class ErrorDatos(ValueError):
    """Dato inválido enviado por el cliente (se responde con 400)."""


def monto_a_centimos(valor) -> int:
    try:
        monto = Decimal(str(valor).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        raise ErrorDatos("El monto no es válido.")
    if not monto.is_finite() or monto <= 0:
        raise ErrorDatos("El monto debe ser mayor a cero.")
    centimos = int((monto * 100).to_integral_value())
    if centimos < 1 or centimos > MAX_MONTO_CENTIMOS:
        raise ErrorDatos("El monto no es válido.")
    return centimos


def fecha_valida(valor) -> str:
    texto = str(valor or "").strip()
    if not RE_FECHA.fullmatch(texto):
        raise ErrorDatos("La fecha debe tener formato AAAA-MM-DD.")
    try:
        f = date.fromisoformat(texto)
    except ValueError:
        raise ErrorDatos("Esa fecha no existe.")
    if f > tiempo.hoy():
        raise ErrorDatos("La fecha no puede ser futura.")
    if f.year < 2000:
        raise ErrorDatos("La fecha es demasiado antigua.")
    return texto


def texto_valido(valor, campo: str, maximo: int = MAX_CONCEPTO) -> str:
    texto = re.sub(r"\s+", " ", str(valor or "")).strip()
    if not texto:
        raise ErrorDatos(f"Falta {campo}.")
    if len(texto) > maximo:
        raise ErrorDatos(f"{campo.capitalize()}: máximo {maximo} caracteres.")
    return texto


def mes_valido(valor) -> str:
    mes = valor or db.hoy()[:7]
    if not RE_MES.fullmatch(mes):
        raise ErrorDatos("Mes inválido. Usa AAAA-MM.")
    return mes


def csv_seguro(valor):
    """Evita que Excel ejecute como fórmula un texto que empieza con = + - @."""
    if isinstance(valor, str) and valor[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + valor
    return valor


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)
    dev = os.environ.get("PLATA_DEV") == "1"

    app.config.update(
        PG_SCHEMA=os.environ.get("PG_SCHEMA", "public"),
        SECRET_KEY=os.environ.get("PLATA_SECRET", "dev-secret" if dev else ""),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("PLATA_HTTPS") == "1",
        PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30,
        LOGIN_INTENTOS_MAX=5,
        AUTENTICAR=usuarios_pg.verificar,
    )
    if config:
        app.config.update(config)

    if not app.config["SECRET_KEY"]:
        raise RuntimeError(
            "Falta PLATA_SECRET. Para probar en local usa PLATA_DEV=1."
        )

    db.configurar(app.config["PG_SCHEMA"])
    if not app.config.get("TESTING"):
        # En pruebas, la clase de test crea el esquema una sola vez (setUpClass)
        # y lo vacía entre tests; repetir esto en cada create_app() sería mucho
        # más lento contra el Postgres real sin aportar nada.
        db.iniciar()

    def sincronizar_admin():
        """Vuelve a leer PLATA_ADMIN_USER/PASSWORD del .env (por si cambiaron) y los
        aplica en Postgres. Así no hace falta reiniciar la app tras editar el .env."""
        if app.config.get("TESTING"):
            return
        load_dotenv(override=True)
        admin_usuario = os.environ.get("PLATA_ADMIN_USER")
        admin_clave = os.environ.get("PLATA_ADMIN_PASSWORD")
        if admin_usuario and admin_clave:
            try:
                usuarios_pg.crear_usuario(admin_usuario, admin_clave)
            except Exception as e:
                print(f"Aviso: no se pudo crear/actualizar el usuario admin desde .env: {e}")

    sincronizar_admin()

    def requiere_login(vista):
        @wraps(vista)
        def envoltura(*args, **kwargs):
            if not session.get("ok"):
                if request.path.startswith("/api/"):
                    return jsonify(error="No autorizado"), 401
                return redirect(url_for("login"))
            return vista(*args, **kwargs)

        return envoltura

    def api(vista):
        """Login obligatorio y errores de datos como JSON 400."""
        @wraps(vista)
        @requiere_login
        def envoltura(*args, **kwargs):
            try:
                return vista(*args, **kwargs)
            except (ErrorDatos, ErrorParser, db.ErrorCategoria) as e:
                return jsonify(error=str(e)), 400

        return envoltura

    def cuerpo() -> dict:
        datos = request.get_json(silent=True)
        return datos if isinstance(datos, dict) else {}

    def cats(tipo: str) -> list[str]:
        return db.categorias(tipo)

    def aprendida(tipo: str, tokens: list[str]):
        return db.categoria_aprendida(tipo, tokens)

    def estatico(filename: str) -> str:
        """url_for('static', ...) con un ?v= según la fecha de modificación del
        archivo: permite cachear fuerte en el navegador sin servir versiones
        viejas cuando el archivo cambia (clave para que la navegación entre
        páginas no vuelva a descargar todo el CSS/JS cada vez)."""
        ruta = os.path.join(app.static_folder, filename)
        try:
            v = int(os.path.getmtime(ruta))
        except OSError:
            v = 0
        return url_for("static", filename=filename, v=v)

    @app.context_processor
    def globales():
        return {
            "app_nombre": APP_NOMBRE,
            "categorias": cats("gasto"),
            "categorias_ingreso": cats("ingreso"),
            "estatico": estatico,
        }

    @app.after_request
    def cabeceras(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        if request.path.startswith("/static/"):
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif request.path.startswith("/api/") or request.path == "/login":
            resp.headers["Cache-Control"] = "no-store"
        return resp

    # ---------- Páginas ----------

    fallos_login: dict[str, list[float]] = {}

    def login_bloqueado(ip: str) -> bool:
        ahora = time.monotonic()
        recientes = [t for t in fallos_login.get(ip, []) if ahora - t < VENTANA_LOGIN_SEG]
        if recientes:
            fallos_login[ip] = recientes
        else:
            fallos_login.pop(ip, None)
        return len(recientes) >= app.config["LOGIN_INTENTOS_MAX"]

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error, estado = None, 200
        if request.method == "POST":
            ip = request.remote_addr or "?"
            usuario = request.form.get("usuario", "")
            clave = request.form.get("clave", "")
            if login_bloqueado(ip):
                error, estado = "Demasiados intentos. Espera unos minutos e inténtalo de nuevo.", 429
                return render_template("login.html", error=error), estado
            sincronizar_admin()
            if app.config["AUTENTICAR"](usuario, clave):
                fallos_login.pop(ip, None)
                session.clear()
                session["ok"] = True
                session["usuario"] = usuario.strip()
                session.permanent = True
                return redirect(url_for("inicio"))
            else:
                if len(fallos_login) > 1000:
                    fallos_login.clear()
                fallos_login.setdefault(ip, []).append(time.monotonic())
                error, estado = "Usuario o clave incorrectos.", 401
        return render_template("login.html", error=error), estado

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    def pagina(nombre: str, clave: str):
        @requiere_login
        def vista():
            extra = {}
            if clave == "inicio":
                extra["mas_usadas"] = {
                    "gasto": db.categorias_mas_usadas("gasto"),
                    "ingreso": db.categorias_mas_usadas("ingreso"),
                }
            return render_template(f"{nombre}.html", pagina=clave, mes_actual=db.hoy()[:7], hoy=db.hoy(), **extra)

        vista.__name__ = clave
        app.add_url_rule({"inicio": "/"}.get(clave, f"/{clave}"), endpoint=clave, view_func=vista)

    for clave in ("inicio", "movimientos", "resumen", "planificacion", "deudas", "historial"):
        pagina(clave, clave)

    @app.get("/exportar.csv")
    @requiere_login
    def exportar():
        salida = io.StringIO()
        salida.write("﻿")  # BOM para que Excel lea bien las tildes
        escritor = csv.writer(salida)
        escritor.writerow(["tipo", "fecha", "concepto", "categoria", "monto_soles", "texto_original"])
        for m in db.todos_los_movimientos():
            escritor.writerow([
                m["tipo"], m["fecha"], csv_seguro(m["concepto"]), m["categoria"],
                f"{m['monto_centimos'] / 100:.2f}", csv_seguro(m["texto"]),
            ])
        nombre = f"tusgastos-{db.hoy()}.csv"
        return Response(salida.getvalue(), mimetype="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{nombre}"'})

    # ---------- PWA (públicas: el navegador las pide sin sesión) ----------

    @app.get("/manifest.webmanifest")
    def manifest():
        return jsonify({
            "name": APP_NOMBRE,
            "short_name": APP_NOMBRE,
            "description": "Anota tus gastos en una línea y sabe cuánto te queda.",
            "lang": "es-PE",
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "background_color": "#f4f6f4",
            "theme_color": "#178a5f",
            "icons": [
                {"src": url_for("static", filename="icons/icon-192.png"), "sizes": "192x192", "type": "image/png"},
                {"src": url_for("static", filename="icons/icon-512.png"), "sizes": "512x512", "type": "image/png"},
                {"src": url_for("static", filename="icons/icon-maskable-512.png"), "sizes": "512x512",
                 "type": "image/png", "purpose": "maskable"},
            ],
        })

    @app.get("/sw.js")
    def service_worker():
        resp = send_from_directory(app.static_folder, "sw.js", mimetype="text/javascript")
        resp.headers["Service-Worker-Allowed"] = "/"
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    # ---------- API: registro por texto ----------

    def resumen_creado(tipo: str, fila: dict, **extra) -> dict:
        return {"tipo": tipo, **fila, **extra}

    @app.post("/api/registrar")
    @api
    def registrar():
        datos = cuerpo()
        texto = str(datos.get("texto", "")).strip()
        if len(texto) > MAX_TEXTO:
            raise ErrorDatos(f"Máximo {MAX_TEXTO} caracteres.")
        # fecha y categoría elegidas en pantalla: solo rellenan lo que el texto no dijo
        fecha_defecto = fecha_valida(datos["fecha"]) if datos.get("fecha") else None
        elegida = datos.get("categoria") or None
        if elegida is not None:
            if not isinstance(elegida, str) or elegida not in set(cats("gasto")) | set(cats("ingreso")):
                raise ErrorDatos("Categoría no válida.")
        movimientos = parsear_varios(texto, aprendida=aprendida)  # si algo falla, no se guarda nada
        creados = []
        for m in movimientos:
            fecha = m.fecha.strftime("%Y-%m-%d") if m.fecha else fecha_defecto
            if m.tipo in ("gasto", "ingreso"):
                tabla = "gastos" if m.tipo == "gasto" else "ingresos"
                categoria, dudosa = m.categoria, m.dudosa
                if elegida and elegida != SIN_CLASIFICAR and elegida in cats(m.tipo):
                    categoria, dudosa = elegida, False
                    db.aprender(m.tipo, tokens_significativos(m.concepto), categoria)
                fila = db.insertar(tabla, texto, m.concepto, m.monto_centimos, categoria, fecha,
                                   categoria_auto=m.categoria)
                creados.append(resumen_creado(m.tipo, fila, categoria_dudosa=dudosa))
            else:
                deuda = db.crear_deuda(m.persona, m.monto_centimos, m.tipo, fecha=fecha)
                gasto = deuda.pop("gasto")
                creados.append(resumen_creado(m.tipo, deuda, concepto=m.concepto, categoria="Deudas"))
                if gasto:
                    creados.append(resumen_creado("gasto", gasto, auxiliar=True))
        return jsonify(creados=creados), 201

    # ---------- API: movimientos (gastos e ingresos) ----------

    def rutas_movimiento(tabla: str, tipo: str):
        def leer_campos(datos: dict, exigir: bool) -> dict:
            campos = {}
            if exigir or "concepto" in datos:
                campos["concepto"] = texto_valido(datos.get("concepto"), "el concepto")
            if exigir or "monto" in datos:
                campos["monto_centimos"] = monto_a_centimos(datos.get("monto"))
            if "fecha" in datos and datos["fecha"] not in (None, ""):
                campos["fecha"] = fecha_valida(datos["fecha"])
            if "categoria" in datos and datos["categoria"] not in (None, ""):
                if datos["categoria"] not in cats(tipo):
                    raise ErrorDatos("Categoría no válida.")
                campos["categoria"] = datos["categoria"]
            return campos

        @api
        def crear():
            campos = leer_campos(cuerpo(), exigir=True)
            sugerida, _ = clasificar(tipo, campos["concepto"], aprendida)
            elegida = campos.get("categoria")
            if not elegida or elegida == SIN_CLASIFICAR:
                categoria = sugerida
            else:
                categoria = elegida
                db.aprender(tipo, tokens_significativos(campos["concepto"]), categoria)
            fila = db.insertar(tabla, campos["concepto"], campos["concepto"],
                               campos["monto_centimos"], categoria, campos.get("fecha"), categoria_auto=sugerida)
            return jsonify(fila), 201

        @api
        def editar(mov_id):
            campos = leer_campos(cuerpo(), exigir=False)
            if not campos:
                raise ErrorDatos("No hay nada que cambiar.")
            previo = db.obtener(tabla, mov_id)
            fila = db.actualizar(tabla, mov_id, campos)
            if fila is None:
                return jsonify(error="No existe."), 404
            if previo and campos.get("categoria") and campos["categoria"] != previo["categoria"]:
                # el usuario corrigió la categoría: la app lo recuerda para la próxima vez
                db.aprender(tipo, tokens_significativos(fila["concepto"]), campos["categoria"])
            return jsonify(fila)

        @api
        def borrar(mov_id):
            if not db.borrar(tabla, mov_id):
                return jsonify(error="No existe."), 404
            return "", 204

        @api
        def recientes():
            return jsonify(db.recientes(30, tabla))

        base = f"/api/{tabla}"
        app.add_url_rule(base, f"crear_{tabla}", crear, methods=["POST"])
        app.add_url_rule(base, f"recientes_{tabla}", recientes, methods=["GET"])
        app.add_url_rule(f"{base}/<int:mov_id>", f"editar_{tabla}", editar, methods=["PATCH"])
        app.add_url_rule(f"{base}/<int:mov_id>", f"borrar_{tabla}", borrar, methods=["DELETE"])

    rutas_movimiento("gastos", "gasto")
    rutas_movimiento("ingresos", "ingreso")

    @app.get("/api/movimientos")
    @api
    def api_movimientos():
        tipo = request.args.get("tipo", "gastos")
        if tipo not in db.TABLAS:
            raise ErrorDatos("Tipo no válido.")
        mes = mes_valido(request.args.get("mes"))
        q = (request.args.get("q") or "").strip()[:60]
        categoria = request.args.get("categoria") or None
        if categoria and categoria not in cats("gasto" if tipo == "gastos" else "ingreso"):
            raise ErrorDatos("Categoría no válida.")
        db.generar_fijos()
        return jsonify(
            items=db.listar(tipo, mes=mes, q=q or None, categoria=categoria),
            resumen=db.resumen_movimientos(tipo, mes),
        )

    # ---------- API: resumen e inicio ----------

    @app.get("/api/resumen")
    @api
    def api_resumen():
        mes = mes_valido(request.args.get("mes"))
        db.generar_fijos()
        return jsonify(db.resumen_mes(mes))

    @app.get("/api/inicio")
    @api
    def api_inicio():
        return jsonify(db.inicio())

    @app.get("/api/sugerir")
    @api
    def api_sugerir():
        """Categoría que la app adivinaría para un detalle (o null si no lo reconoce)."""
        tipo = request.args.get("tipo", "gasto")
        if tipo not in ("gasto", "ingreso"):
            raise ErrorDatos("Tipo no válido.")
        concepto = (request.args.get("concepto") or "").strip()[:MAX_CONCEPTO]
        if not concepto:
            return jsonify(categoria=None)
        categoria, dudosa = clasificar(tipo, concepto, aprendida)
        return jsonify(categoria=None if dudosa else categoria)

    # ---------- API: categorías ----------

    @app.get("/api/categorias")
    @api
    def api_categorias():
        return jsonify(gasto=db.listar_categorias("gasto"),
                       ingreso=db.listar_categorias("ingreso"))

    @app.post("/api/categorias")
    @api
    def api_crear_categoria():
        datos = cuerpo()
        return jsonify(db.crear_categoria(datos.get("tipo"), datos.get("nombre"))), 201

    @app.patch("/api/categorias/<tipo>/<nombre>")
    @api
    def api_renombrar_categoria(tipo, nombre):
        return jsonify(db.renombrar_categoria(tipo, nombre, cuerpo().get("nombre")))

    @app.delete("/api/categorias/<tipo>/<nombre>")
    @api
    def api_borrar_categoria(tipo, nombre):
        try:
            db.borrar_categoria(tipo, nombre)
        except db.ErrorCategoria as e:
            estado = 409 if "Todavía tiene" in str(e) else 400
            return jsonify(error=str(e)), estado
        return "", 204

    # ---------- API: topes por categoría ----------

    @app.get("/api/topes")
    @api
    def listar_topes():
        return jsonify(db.estado_topes(mes_valido(request.args.get("mes"))))

    @app.put("/api/topes/<categoria>")
    @api
    def guardar_tope(categoria):
        if categoria == SIN_CLASIFICAR or categoria not in cats("gasto"):
            raise ErrorDatos("Categoría no válida.")
        db.guardar_tope(categoria, monto_a_centimos(cuerpo().get("monto")))
        return jsonify(db.estado_topes(db.hoy()[:7], [categoria])[0])

    @app.delete("/api/topes/<categoria>")
    @api
    def borrar_tope(categoria):
        if not db.borrar_tope(categoria):
            return jsonify(error="No existe."), 404
        return "", 204

    # ---------- API: gastos fijos ----------

    def leer_fijo(datos: dict, exigir: bool) -> dict:
        campos = {}
        if exigir or "concepto" in datos:
            campos["concepto"] = texto_valido(datos.get("concepto"), "el concepto")
        if exigir or "monto" in datos:
            campos["monto_centimos"] = monto_a_centimos(datos.get("monto"))
        if exigir or "categoria" in datos:
            if datos.get("categoria") not in cats("gasto"):
                raise ErrorDatos("Categoría no válida.")
            campos["categoria"] = datos["categoria"]
        if exigir or "dia" in datos:
            try:
                dia = int(datos.get("dia"))
            except (TypeError, ValueError):
                raise ErrorDatos("El día debe ser un número del 1 al 31.")
            if not 1 <= dia <= 31:
                raise ErrorDatos("El día debe ser del 1 al 31.")
            campos["dia"] = dia
        if "activo" in datos:
            if not isinstance(datos["activo"], bool):
                raise ErrorDatos("Activo debe ser verdadero o falso.")
            campos["activo"] = datos["activo"]
        return campos

    @app.get("/api/fijos")
    @api
    def listar_fijos():
        return jsonify(db.listar_fijos())

    @app.post("/api/fijos")
    @api
    def crear_fijo():
        c = leer_fijo(cuerpo(), exigir=True)
        fijo = db.crear_fijo(c["concepto"], c["monto_centimos"], c["categoria"], c["dia"])
        return jsonify(fijo), 201

    @app.patch("/api/fijos/<int:fijo_id>")
    @api
    def editar_fijo(fijo_id):
        campos = leer_fijo(cuerpo(), exigir=False)
        if not campos:
            raise ErrorDatos("No hay nada que cambiar.")
        fijo = db.actualizar_fijo(fijo_id, campos)
        if fijo is None:
            return jsonify(error="No existe."), 404
        return jsonify(fijo)

    @app.delete("/api/fijos/<int:fijo_id>")
    @api
    def borrar_fijo(fijo_id):
        if not db.borrar_fijo(fijo_id):
            return jsonify(error="No existe."), 404
        return "", 204

    # ---------- API: deudas ----------

    @app.get("/api/deudas")
    @api
    def listar_deudas():
        pagadas = request.args.get("pagadas") == "1"
        return jsonify(deudas=db.listar_deudas(incluir_pagadas=pagadas),
                       resumen=db.resumen_deudas())

    @app.post("/api/deudas")
    @api
    def crear_deuda():
        datos = cuerpo()
        tipo = datos.get("tipo")
        if tipo not in ("me_deben", "debo"):
            raise ErrorDatos("Indica si te deben o si debes.")
        persona = texto_valido(datos.get("persona"), "el nombre de la persona", 60)
        nota = str(datos.get("nota") or "").strip()[:120]
        fecha = fecha_valida(datos["fecha"]) if datos.get("fecha") else None
        deuda = db.crear_deuda(persona, monto_a_centimos(datos.get("monto")), tipo, nota, fecha)
        return jsonify(deuda), 201

    @app.post("/api/deudas/<int:deuda_id>/pagar")
    @api
    def pagar_deuda(deuda_id):
        try:
            deuda = db.pagar_deuda(deuda_id)
        except ValueError as e:
            return jsonify(error=str(e)), 409
        if deuda is None:
            return jsonify(error="No existe."), 404
        return jsonify(deuda)

    @app.delete("/api/deudas/<int:deuda_id>")
    @api
    def borrar_deuda(deuda_id):
        if not db.borrar_deuda(deuda_id):
            return jsonify(error="No existe."), 404
        return "", 204

    # ---------- API: historial de borrados ----------

    @app.get("/api/historial")
    @api
    def api_historial():
        return jsonify(db.listar_borrados())

    return app


if __name__ == "__main__":
    app = create_app()
    app.jinja_env.auto_reload = True  # recoge cambios en las plantillas sin reiniciar
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")))
