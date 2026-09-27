import calendar
import os
import sys
import time
import unittest
import uuid
from contextlib import closing
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402
import tiempo  # noqa: E402
from app import create_app  # noqa: E402


def congelar(anio, mes, dia, hora=12):
    ahora = datetime(anio, mes, dia, hora, 0, tzinfo=tiempo.LIMA)
    return patch.multiple("tiempo", ahora=lambda: ahora, hoy=lambda: ahora.date())


class BaseApp(unittest.TestCase):
    """Cada clase de test tiene su propio esquema de Postgres, creado una sola
    vez (setUpClass) y borrado al final (tearDownClass). Crear/borrar el
    esquema completo en cada test individual era correcto pero carísimo
    contra un Postgres remoto (~12s por test); en vez de eso, cada test
    arranca con las tablas vacías (TRUNCATE), mucho más barato."""

    @classmethod
    def setUpClass(cls):
        cls.schema = f"test_{uuid.uuid4().hex[:12]}"
        db.configurar(cls.schema)
        db.iniciar()

    @classmethod
    def tearDownClass(cls):
        with closing(db.conectar()) as con, con.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{cls.schema}" CASCADE')
            con.commit()

    def setUp(self):
        db.configurar(self.schema)
        with closing(db.conectar()) as con, con.cursor() as cur:
            cur.execute(
                "TRUNCATE gastos, ingresos, topes, fijos, deudas, categorias, aprendido, borrados"
                " RESTART IDENTITY CASCADE"
            )
            con.commit()
        self.app = create_app({
            "PG_SCHEMA": self.schema,
            "AUTENTICAR": lambda usuario, clave: (usuario, clave) == ("prueba", "clave-de-prueba"),
            "SECRET_KEY": "secreto-de-prueba",
            "TESTING": True,
        })
        self.cli = self.app.test_client()

    def entrar(self):
        return self.cli.post("/login", data={"usuario": "prueba", "clave": "clave-de-prueba"})

    def reg(self, texto, esperado=201):
        r = self.cli.post("/api/registrar", json={"texto": texto})
        self.assertEqual(r.status_code, esperado, r.get_data(as_text=True))
        return r.get_json()


class BaseLogueado(BaseApp):
    def setUp(self):
        super().setUp()
        self.entrar()


class TestAcceso(BaseApp):
    def test_api_sin_login_da_401(self):
        for metodo, ruta in [("get", "/api/inicio"), ("get", "/api/movimientos"), ("get", "/api/resumen"),
                             ("get", "/api/topes"), ("get", "/api/fijos"), ("get", "/api/deudas"),
                             ("post", "/api/registrar"), ("post", "/api/deudas")]:
            self.assertEqual(getattr(self.cli, metodo)(ruta).status_code, 401, ruta)

    def test_paginas_sin_login_redirigen(self):
        for ruta in ["/", "/movimientos", "/resumen", "/planificacion", "/deudas", "/historial", "/exportar.csv"]:
            r = self.cli.get(ruta)
            self.assertEqual(r.status_code, 302, ruta)
            self.assertIn("/login", r.headers["Location"])

    def test_clave_incorrecta(self):
        r = self.cli.post("/login", data={"usuario": "prueba", "clave": "mala"})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(self.cli.get("/api/inicio").status_code, 401)

    def test_login_y_logout(self):
        self.assertEqual(self.entrar().status_code, 302)
        self.assertEqual(self.cli.get("/api/inicio").status_code, 200)
        self.cli.post("/logout")
        self.assertEqual(self.cli.get("/api/inicio").status_code, 401)

    def test_bloquea_tras_demasiados_intentos_y_se_libera(self):
        for _ in range(5):
            self.assertEqual(self.cli.post("/login", data={"clave": "mala"}).status_code, 401)
        # aun con la clave correcta, mientras dure el bloqueo
        self.assertEqual(self.entrar().status_code, 429)
        self.assertEqual(self.cli.get("/api/inicio").status_code, 401)
        ahora = time.monotonic()
        with patch("app.time.monotonic", return_value=ahora + 301):
            self.assertEqual(self.entrar().status_code, 302)

    def test_un_acierto_reinicia_el_conteo(self):
        for _ in range(4):
            self.cli.post("/login", data={"clave": "mala"})
        self.assertEqual(self.entrar().status_code, 302)
        for _ in range(4):
            self.assertEqual(self.cli.post("/login", data={"clave": "mala"}).status_code, 401)

    def test_sin_configuracion_no_arranca(self):
        with self.assertRaises(RuntimeError):
            create_app({"SECRET_KEY": ""})


class TestPaginas(BaseApp):
    def test_login_sin_menu_lateral(self):
        r = self.cli.get("/login")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn(b"navbar-vertical", r.data)
        self.assertIn(b"TusGastos", r.data)

    def test_paginas_con_menu_y_ruta_activa(self):
        self.entrar()
        for ruta in ["/", "/movimientos", "/resumen", "/planificacion", "/deudas", "/historial"]:
            r = self.cli.get(ruta)
            self.assertEqual(r.status_code, 200, ruta)
            self.assertIn(b"navbar-vertical", r.data, ruta)
            self.assertIn(b"TusGastos", r.data, ruta)
            self.assertNotIn(b"Escenarios", r.data, ruta)
            self.assertNotIn(b"barra-inferior", r.data, ruta)
            self.assertIn(b"navbar-toggler", r.data, ruta)  # hamburguesa solo para el celular
            self.assertEqual(r.data.count(b'aria-current="page"'), 1, ruta)

    def test_pwa_publica(self):
        m = self.cli.get("/manifest.webmanifest")
        self.assertEqual(m.status_code, 200)
        datos = m.get_json()
        self.assertEqual(datos["short_name"], "TusGastos")
        self.assertEqual(datos["display"], "standalone")
        self.assertTrue(any(i.get("purpose") == "maskable" for i in datos["icons"]))
        sw = self.cli.get("/sw.js")
        self.assertEqual(sw.status_code, 200)
        self.assertEqual(sw.headers["Service-Worker-Allowed"], "/")
        self.assertIn("javascript", sw.headers["Content-Type"])


class TestRegistrar(BaseLogueado):
    def test_gasto_simple(self):
        r = self.reg("almuerzo 18")
        (g,) = r["creados"]
        self.assertEqual((g["tipo"], g["concepto"], g["monto_centimos"], g["categoria"]),
                         ("gasto", "almuerzo", 1800, "Comida"))
        self.assertEqual(g["fecha"], db.hoy())
        self.assertEqual(g["categoria_auto"], "Comida")

    def test_gasto_de_ayer(self):
        (g,) = self.reg("ayer taxi 8")["creados"]
        ayer = (tiempo.hoy() - timedelta(days=1)).strftime("%Y-%m-%d")
        self.assertEqual((g["fecha"], g["monto_centimos"]), (ayer, 800))

    def test_ingreso(self):
        (i,) = self.reg("sueldo 800")["creados"]
        self.assertEqual((i["tipo"], i["categoria"], i["monto_centimos"]), ("ingreso", "Sueldo", 80000))
        self.assertEqual(self.cli.get("/api/movimientos?tipo=gastos").get_json()["items"], [])
        self.assertEqual(len(self.cli.get("/api/movimientos?tipo=ingresos").get_json()["items"]), 1)

    def test_varios_en_una_linea(self):
        creados = self.reg("menú 12, taxi 8 y sueldo 100")["creados"]
        self.assertEqual([c["tipo"] for c in creados], ["gasto", "gasto", "ingreso"])

    def test_un_error_no_guarda_nada(self):
        self.reg("menú 12, taxi", esperado=400)
        self.assertEqual(self.cli.get("/api/movimientos").get_json()["items"], [])

    def test_prestamo_crea_deuda_y_gasto(self):
        creados = self.reg("le presté 25 a Juan")["creados"]
        self.assertEqual([c["tipo"] for c in creados], ["me_deben", "gasto"])
        self.assertEqual(creados[0]["persona"], "Juan")
        self.assertTrue(creados[1]["auxiliar"])
        self.assertEqual(creados[1]["categoria"], "Deudas")
        self.assertEqual(self.cli.get("/api/deudas").get_json()["resumen"]["me_deben_centimos"], 2500)

    def test_lo_que_debo_no_crea_gasto(self):
        creados = self.reg("fiado bodega 15")["creados"]
        self.assertEqual([c["tipo"] for c in creados], ["debo"])
        self.assertEqual(self.cli.get("/api/movimientos").get_json()["items"], [])

    def test_texto_invalido(self):
        self.reg("almuerzo", esperado=400)
        self.reg("x" * 400 + " 5", esperado=400)
        self.assertEqual(self.cli.post("/api/registrar", json={}).status_code, 400)
        self.assertEqual(self.cli.post("/api/registrar", data="no es json").status_code, 400)

    def test_html_se_guarda_como_texto(self):
        (g,) = self.reg("<script>alert(1)</script> 5")["creados"]
        self.assertIn("<script>", g["concepto"])


class TestMovimientos(BaseLogueado):
    def test_crear_manual_con_fecha_y_categoria_sugerida(self):
        r = self.cli.post("/api/gastos", json={"concepto": "taxi", "monto": "12.50", "fecha": "2026-01-05"})
        self.assertEqual(r.status_code, 201)
        g = r.get_json()
        self.assertEqual((g["monto_centimos"], g["fecha"], g["categoria"]), (1250, "2026-01-05", "Transporte"))

    def test_crear_ingreso_manual(self):
        r = self.cli.post("/api/ingresos", json={"concepto": "sueldo", "monto": 900, "categoria": "Sueldo"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.get_json()["monto_centimos"], 90000)

    def test_validaciones(self):
        for datos in [
            {"concepto": "", "monto": 5},
            {"concepto": "taxi", "monto": 0},
            {"concepto": "taxi", "monto": -3},
            {"concepto": "taxi", "monto": "abc"},
            {"concepto": "taxi", "monto": "NaN"},
            {"concepto": "taxi", "monto": 99999999999},
            {"concepto": "taxi", "monto": 5, "fecha": "2999-01-01"},
            {"concepto": "taxi", "monto": 5, "fecha": "2026-02-30"},
            {"concepto": "taxi", "monto": 5, "fecha": "ayer"},
            {"concepto": "taxi", "monto": 5, "categoria": "Inventada"},
            {"concepto": "x" * 101, "monto": 5},
        ]:
            self.assertEqual(self.cli.post("/api/gastos", json=datos).status_code, 400, datos)

    def test_categoria_de_ingreso_no_vale_para_gasto(self):
        r = self.cli.post("/api/gastos", json={"concepto": "taxi", "monto": 5, "categoria": "Sueldo"})
        self.assertEqual(r.status_code, 400)

    def test_editar_todo_conserva_categoria_automatica(self):
        g = self.reg("zzz 50")["creados"][0]
        r = self.cli.patch(f"/api/gastos/{g['id']}", json={
            "concepto": "regalo mamá", "monto": "55.5", "fecha": "2026-01-02", "categoria": "Ocio"})
        self.assertEqual(r.status_code, 200)
        e = r.get_json()
        self.assertEqual((e["concepto"], e["monto_centimos"], e["fecha"], e["categoria"]),
                         ("regalo mamá", 5550, "2026-01-02", "Ocio"))
        self.assertEqual(e["categoria_auto"], "Sin clasificar")

    def test_editar_parcial_e_invalido(self):
        g = self.reg("taxi 10")["creados"][0]
        r = self.cli.patch(f"/api/gastos/{g['id']}", json={"categoria": "Ocio"})
        self.assertEqual(r.get_json()["monto_centimos"], 1000)
        self.assertEqual(self.cli.patch(f"/api/gastos/{g['id']}", json={}).status_code, 400)
        self.assertEqual(self.cli.patch(f"/api/gastos/{g['id']}", json={"monto": -1}).status_code, 400)
        self.assertEqual(self.cli.patch("/api/gastos/9999", json={"categoria": "Ocio"}).status_code, 404)

    def test_borrar(self):
        g = self.reg("taxi 10")["creados"][0]
        self.assertEqual(self.cli.delete(f"/api/gastos/{g['id']}").status_code, 204)
        self.assertEqual(self.cli.delete(f"/api/gastos/{g['id']}").status_code, 404)

    def test_listar_con_filtros(self):
        for texto in ["almuerzo 18", "menú 12", "taxi 8", "chelas 30 el 1"]:
            self.reg(texto)
        todos = self.cli.get("/api/movimientos").get_json()
        self.assertEqual(len(todos["items"]), 4)
        self.assertEqual(todos["resumen"]["total_centimos"], 6800)
        por_texto = self.cli.get("/api/movimientos?q=alm").get_json()["items"]
        self.assertEqual([m["concepto"] for m in por_texto], ["almuerzo"])
        por_categoria = self.cli.get("/api/movimientos?categoria=Transporte").get_json()["items"]
        self.assertEqual([m["concepto"] for m in por_categoria], ["taxi"])
        self.assertEqual(self.cli.get("/api/movimientos?mes=2020-01").get_json()["items"], [])

    def test_busqueda_trata_porcentaje_como_texto(self):
        self.reg("descuento 50% tienda 20")
        self.reg("almuerzo 18")
        items = self.cli.get("/api/movimientos?q=%25").get_json()["items"]
        self.assertEqual([m["concepto"] for m in items], ["descuento 50% tienda"])

    def test_orden_por_fecha_mas_reciente(self):
        self.reg("taxi 5 hace 3 días")
        self.reg("menú 12")
        fechas = [m["fecha"] for m in self.cli.get("/api/movimientos").get_json()["items"]]
        self.assertEqual(fechas, sorted(fechas, reverse=True))

    def test_parametros_invalidos(self):
        self.assertEqual(self.cli.get("/api/movimientos?tipo=otra").status_code, 400)
        self.assertEqual(self.cli.get("/api/movimientos?mes=2020-13").status_code, 400)
        self.assertEqual(self.cli.get("/api/movimientos?categoria=Inventada").status_code, 400)


class TestResumen(BaseLogueado):
    def test_resumen_del_mes(self):
        for texto in ["almuerzo 20", "menú 10", "taxi 10", "delivery 60", "sueldo 500"]:
            self.reg(texto)
        r = self.cli.get("/api/resumen").get_json()
        self.assertEqual(r["total_centimos"], 10000)
        self.assertEqual(r["ingresos_centimos"], 50000)
        self.assertEqual(r["n_gastos"], 4)
        self.assertEqual(r["categoria_top"], "Delivery")
        self.assertEqual(r["dias_con_registro"], 1)
        porcentajes = {c["categoria"]: c["porcentaje"] for c in r["categorias"]}
        self.assertEqual(porcentajes, {"Delivery": 60.0, "Comida": 30.0, "Transporte": 10.0})

    def test_datos_por_dia_del_mes_actual(self):
        for texto in ["almuerzo 20", "menú 10", "delivery 60"]:
            self.reg(texto)
        r = self.cli.get("/api/resumen").get_json()
        dia = int(db.hoy()[8:10])
        anio, mes = int(db.hoy()[:4]), int(db.hoy()[5:7])
        dias_mes = calendar.monthrange(anio, mes)[1]
        self.assertEqual(r["dias_transcurridos"], dia)
        # El gráfico siempre muestra el mes completo (1 al último día), no solo lo transcurrido.
        self.assertEqual(len(r["por_dia_centimos"]), dias_mes)
        self.assertEqual(r["por_dia_centimos"][dia - 1], 9000)
        self.assertEqual(r["por_dia_centimos"][dia:], [0] * (dias_mes - dia))
        self.assertEqual(r["dia_mayor"], {"dia": dia, "total_centimos": 9000})
        self.assertEqual(r["promedio_diario_centimos"], round(9000 / dia))
        self.assertEqual([g["concepto"] for g in r["ultimos"]], ["delivery", "menú", "almuerzo"])

    def test_mes_vacio_pasado_y_futuro(self):
        r = self.cli.get("/api/resumen?mes=2020-01").get_json()
        self.assertEqual((r["total_centimos"], r["dias_transcurridos"], r["mes_anterior"]), (0, 31, "2019-12"))
        self.assertIsNone(r["dia_mayor"])
        f = self.cli.get("/api/resumen?mes=2099-05").get_json()
        self.assertEqual((f["dias_transcurridos"], f["por_dia_centimos"]), (0, [0] * 31))

    def test_mes_invalido(self):
        self.assertEqual(self.cli.get("/api/resumen?mes=2020-13").status_code, 400)
        self.assertEqual(self.cli.get("/api/resumen?mes=abc").status_code, 400)


class TestInicio(BaseLogueado):
    def test_dia_sin_registros(self):
        with congelar(2026, 9, 26):
            r = self.cli.get("/api/inicio").get_json()
        self.assertTrue(r["sin_registro_hoy"])
        self.assertEqual((r["disponible_centimos"], r["por_dia_centimos"]), (0, 0))
        self.assertEqual(r["dias_restantes"], 5)

    def test_cuanto_te_queda(self):
        with congelar(2026, 9, 26):
            self.reg("sueldo 800")
            self.reg("almuerzo 100, taxi 50")
            r = self.cli.get("/api/inicio").get_json()
        self.assertEqual(r["ingresado_mes_centimos"], 80000)
        self.assertEqual(r["gastado_mes_centimos"], 15000)
        self.assertEqual(r["disponible_centimos"], 65000)
        self.assertEqual(r["por_dia_centimos"], 65000 // 5)  # quedan 5 días contando hoy
        self.assertEqual((r["gasto_hoy_centimos"], r["n_hoy"], r["sin_registro_hoy"]), (15000, 2, False))

    def test_sin_disponible_no_hay_monto_por_dia(self):
        self.reg("sueldo 100")
        self.reg("almuerzo 150")
        r = self.cli.get("/api/inicio").get_json()
        self.assertEqual((r["disponible_centimos"], r["por_dia_centimos"]), (-5000, 0))

    def test_gasto_de_ayer_no_cuenta_como_hoy(self):
        self.reg("ayer almuerzo 18")
        self.assertTrue(self.cli.get("/api/inicio").get_json()["sin_registro_hoy"])

    def test_frecuentes(self):
        for _ in range(3):
            self.reg("menú 12")
        self.reg("taxi 8")
        f = self.cli.get("/api/inicio").get_json()["frecuentes"]
        self.assertEqual([(x["concepto"], x["monto_centimos"], x["veces"]) for x in f], [("menú", 1200, 3)])

    def test_ultimos_mezclan_gastos_e_ingresos(self):
        self.reg("menú 12")
        self.reg("sueldo 500")
        tipos = [u["tipo"] for u in self.cli.get("/api/inicio").get_json()["ultimos"]]
        self.assertEqual(tipos, ["ingreso", "gasto"])


class TestRegistros(BaseLogueado):
    def inicio(self):
        return self.cli.get("/api/inicio").get_json()

    def test_lo_anotado_hoy_incluye_lo_de_otros_dias_y_los_ingresos(self):
        self.reg("ayer taxi 8")
        self.reg("menú 12")
        self.reg("sueldo 100")
        anotados = self.inicio()["anotados_hoy"]
        self.assertEqual([(a["concepto"], a["tipo"]) for a in anotados],
                         [("sueldo", "ingreso"), ("menú", "gasto"), ("taxi", "gasto")])

    def test_lo_anotado_hoy_no_incluye_los_gastos_fijos_automaticos(self):
        with congelar(2026, 9, 1):
            self.cli.post("/api/fijos", json={"concepto": "alquiler", "monto": 500, "categoria": "Hogar", "dia": 2})
        with congelar(2026, 9, 10):
            self.reg("menú 12")
            i = self.inicio()
            self.assertEqual([a["concepto"] for a in i["anotados_hoy"]], ["menú"])
            self.assertEqual(len(self.cli.get("/api/movimientos?mes=2026-09").get_json()["items"]), 2)

    def test_lo_anotado_ayer_ya_no_sale_hoy(self):
        with congelar(2026, 9, 9):
            self.reg("menú 12")
        with congelar(2026, 9, 10):
            self.assertEqual(self.inicio()["anotados_hoy"], [])

    def test_mas_usadas_sin_historial_son_las_de_siempre(self):
        m = self.inicio()["mas_usadas"]
        self.assertEqual(m["gasto"], ["Comida", "Transporte", "Mercado", "Servicios", "Salud", "Ocio"])
        self.assertEqual(m["ingreso"], ["Sueldo", "Ventas y cachuelos", "Regalos y apoyo", "Cobro de deudas"])

    def test_mas_usadas_pone_primero_lo_que_mas_usas(self):
        for _ in range(3):
            self.reg("delivery 20")
        self.reg("zapatillas 100")
        self.reg("xyz 5")  # sin clasificar no cuenta
        m = self.inicio()["mas_usadas"]["gasto"]
        self.assertEqual(m[:2], ["Delivery", "Ropa y calzado"])
        self.assertEqual(len(m), 6)
        self.assertNotIn("Sin clasificar", m)

    def test_mas_usadas_incluye_las_propias(self):
        self.cli.post("/api/categorias", json={"nombre": "Fútbol", "tipo": "gasto"})
        self.cli.post("/api/gastos", json={"concepto": "cancha", "monto": 20, "categoria": "Fútbol"})
        self.assertEqual(self.inicio()["mas_usadas"]["gasto"][0], "Fútbol")

    def test_la_pagina_lleva_las_mas_usadas_y_se_llama_registros(self):
        self.reg("delivery 20")
        r = self.cli.get("/")
        self.assertIn("Registros".encode(), r.data)
        self.assertIn(b'"masUsadas"', r.data.replace(b" ", b"").replace(b"masUsadas:", b'"masUsadas"'))
        self.assertIn(b'"Delivery"', r.data)


class TestTopes(BaseLogueado):
    def tope(self, categoria, monto):
        return self.cli.put(f"/api/topes/{categoria}", json={"monto": monto})

    def test_estados_ok_cerca_pasado(self):
        self.tope("Delivery", 100)
        self.reg("delivery 50")
        estado = {t["categoria"]: t for t in self.cli.get("/api/topes").get_json()}
        self.assertEqual((estado["Delivery"]["estado"], estado["Delivery"]["porcentaje"]), ("ok", 50))
        self.reg("delivery 35")
        delivery = lambda: next(t for t in self.cli.get("/api/topes").get_json() if t["categoria"] == "Delivery")
        self.assertEqual(delivery()["estado"], "cerca")
        self.reg("delivery 20")
        d = next(t for t in self.cli.get("/api/topes").get_json() if t["categoria"] == "Delivery")
        self.assertEqual((d["estado"], d["restante_centimos"]), ("pasado", -500))

    def test_lista_todas_las_categorias_aunque_no_tengan_tope(self):
        estado = self.cli.get("/api/topes").get_json()
        nombres = [t["categoria"] for t in estado]
        self.assertIn("Delivery", nombres)
        self.assertNotIn("Sin clasificar", nombres)  # un tope ahí no tiene sentido
        self.assertTrue(all(t["tope_centimos"] is None and t["estado"] is None for t in estado))

    def test_cambiar_y_borrar(self):
        self.tope("Ocio", 50)
        self.assertEqual(self.tope("Ocio", 80).get_json()["tope_centimos"], 8000)
        self.assertEqual(self.cli.delete("/api/topes/Ocio").status_code, 204)
        self.assertEqual(self.cli.delete("/api/topes/Ocio").status_code, 404)

    def test_validaciones(self):
        self.assertEqual(self.tope("Inventada", 50).status_code, 400)
        self.assertEqual(self.tope("Ocio", 0).status_code, 400)
        self.assertEqual(self.tope("Ocio", "mucho").status_code, 400)

    def test_alertas_en_inicio(self):
        self.tope("Delivery", 100)
        self.tope("Ocio", 100)
        self.reg("delivery 90")
        self.reg("chelas 10")
        i = self.cli.get("/api/inicio").get_json()
        self.assertTrue(i["hay_topes"])
        self.assertEqual([(a["categoria"], a["estado"]) for a in i["alertas"]], [("Delivery", "cerca")])


class TestFijos(BaseLogueado):
    def crear(self, dia, **extra):
        datos = {"concepto": "alquiler", "monto": 500, "categoria": "Hogar", "dia": dia, **extra}
        return self.cli.post("/api/fijos", json=datos)

    def gastos(self):
        return self.cli.get("/api/movimientos").get_json()["items"]

    def test_si_su_dia_ya_paso_no_inventa_gastos_del_pasado(self):
        with congelar(2026, 9, 10):
            self.assertEqual(self.crear(5).status_code, 201)
            self.cli.get("/api/inicio")
            self.assertEqual(self.gastos(), [])
        with congelar(2026, 10, 6):
            self.cli.get("/api/inicio")
            (g,) = self.gastos()
            self.assertEqual((g["fecha"], g["monto_centimos"], g["categoria"]), ("2026-10-05", 50000, "Hogar"))

    def test_se_registra_el_dia_que_llega_y_una_sola_vez(self):
        with congelar(2026, 9, 10):
            self.crear(15)
            self.cli.get("/api/inicio")
            self.assertEqual(self.gastos(), [])
        with congelar(2026, 9, 16):
            for _ in range(3):
                self.cli.get("/api/inicio")
            (g,) = self.gastos()
            self.assertEqual(g["fecha"], "2026-09-15")
        with congelar(2026, 10, 16):
            self.cli.get("/api/inicio")
            self.assertEqual(len(self.cli.get("/api/movimientos?mes=2026-10").get_json()["items"]), 1)

    def test_dia_31_en_mes_de_30(self):
        with congelar(2026, 9, 1):
            self.crear(31)
        with congelar(2026, 9, 29):
            self.cli.get("/api/inicio")
            self.assertEqual(self.gastos(), [])
        with congelar(2026, 9, 30):
            self.cli.get("/api/inicio")
            self.assertEqual(self.gastos()[0]["fecha"], "2026-09-30")

    def test_inactivo_no_se_registra(self):
        with congelar(2026, 9, 1):
            fijo = self.crear(15).get_json()
            r = self.cli.patch(f"/api/fijos/{fijo['id']}", json={"activo": False})
            self.assertFalse(r.get_json()["activo"])
        with congelar(2026, 9, 20):
            self.cli.get("/api/inicio")
            self.assertEqual(self.gastos(), [])

    def test_proximos_en_inicio(self):
        with congelar(2026, 9, 10):
            self.crear(12, concepto="luz")
            self.crear(28, concepto="agua")
            proximos = self.cli.get("/api/inicio").get_json()["proximos_fijos"]
        self.assertEqual([(p["concepto"], p["faltan_dias"]) for p in proximos], [("luz", 2)])

    def test_gasto_fijo_no_cuenta_como_frecuente(self):
        with congelar(2026, 9, 1):
            self.crear(2)
        for dia in (3, 20):
            with congelar(2026, 9 if dia == 3 else 10, 3 if dia == 3 else 20):
                self.cli.get("/api/inicio")
        with congelar(2026, 10, 25):
            self.assertEqual(self.cli.get("/api/inicio").get_json()["frecuentes"], [])

    def test_editar_borrar_y_validar(self):
        fijo = self.crear(15).get_json()
        r = self.cli.patch(f"/api/fijos/{fijo['id']}", json={"monto": 550, "dia": 20})
        self.assertEqual((r.get_json()["monto_centimos"], r.get_json()["dia"]), (55000, 20))
        self.assertEqual(len(self.cli.get("/api/fijos").get_json()), 1)
        self.assertEqual(self.cli.delete(f"/api/fijos/{fijo['id']}").status_code, 204)
        self.assertEqual(self.cli.delete(f"/api/fijos/{fijo['id']}").status_code, 404)
        for datos in [{"dia": 0}, {"dia": 32}, {"dia": "x"}, {"categoria": "Inventada"}, {"concepto": ""}]:
            base = {"concepto": "alquiler", "monto": 500, "categoria": "Hogar", "dia": 5}
            self.assertEqual(self.cli.post("/api/fijos", json={**base, **datos}).status_code, 400, datos)


class TestDeudas(BaseLogueado):
    def crear(self, **extra):
        datos = {"persona": "Juan", "monto": 25, "tipo": "me_deben", **extra}
        return self.cli.post("/api/deudas", json=datos)

    def test_me_deben_tambien_es_un_gasto(self):
        d = self.crear().get_json()
        self.assertEqual(d["monto_centimos"], 2500)
        gastos = self.cli.get("/api/movimientos").get_json()["items"]
        self.assertEqual([(g["concepto"], g["categoria"]) for g in gastos], [("Préstamo a Juan", "Deudas")])

    def test_debo_no_toca_tus_gastos_hasta_pagar(self):
        d = self.crear(tipo="debo", persona="Pedro", monto=30).get_json()
        self.assertEqual(self.cli.get("/api/movimientos").get_json()["items"], [])
        pagada = self.cli.post(f"/api/deudas/{d['id']}/pagar").get_json()
        self.assertEqual(pagada["movimiento"]["tipo"], "gasto")
        self.assertEqual(pagada["pagada_fecha"], db.hoy())
        gastos = self.cli.get("/api/movimientos").get_json()["items"]
        self.assertEqual([(g["concepto"], g["monto_centimos"]) for g in gastos], [("Pago a Pedro", 3000)])

    def test_cobrar_lo_que_me_deben_es_un_ingreso(self):
        d = self.crear().get_json()
        pagada = self.cli.post(f"/api/deudas/{d['id']}/pagar").get_json()
        self.assertEqual(pagada["movimiento"]["tipo"], "ingreso")
        ingresos = self.cli.get("/api/movimientos?tipo=ingresos").get_json()["items"]
        self.assertEqual([(i["concepto"], i["monto_centimos"]) for i in ingresos], [("Cobro a Juan", 2500)])

    def test_no_se_paga_dos_veces(self):
        d = self.crear().get_json()
        self.assertEqual(self.cli.post(f"/api/deudas/{d['id']}/pagar").status_code, 200)
        self.assertEqual(self.cli.post(f"/api/deudas/{d['id']}/pagar").status_code, 409)
        self.assertEqual(self.cli.post("/api/deudas/9999/pagar").status_code, 404)

    def test_listado_y_resumen(self):
        self.crear()
        self.crear(persona="Ana", monto=10)
        d = self.crear(tipo="debo", persona="Pedro", monto=30).get_json()
        r = self.cli.get("/api/deudas").get_json()
        self.assertEqual(len(r["deudas"]), 3)
        self.assertEqual((r["resumen"]["me_deben_centimos"], r["resumen"]["debo_centimos"]), (3500, 3000))
        self.cli.post(f"/api/deudas/{d['id']}/pagar")
        r = self.cli.get("/api/deudas").get_json()
        self.assertEqual(len(r["deudas"]), 2)
        self.assertEqual(r["resumen"]["debo_centimos"], 0)
        self.assertEqual(len(self.cli.get("/api/deudas?pagadas=1").get_json()["deudas"]), 3)

    def test_borrar(self):
        d = self.crear().get_json()
        self.assertEqual(self.cli.delete(f"/api/deudas/{d['id']}").status_code, 204)
        self.assertEqual(self.cli.delete(f"/api/deudas/{d['id']}").status_code, 404)

    def test_validaciones(self):
        for extra in [{"tipo": "otra"}, {"persona": ""}, {"monto": 0}, {"monto": "x"}, {"fecha": "2999-01-01"}]:
            self.assertEqual(self.crear(**extra).status_code, 400, extra)


class TestCategorias(BaseLogueado):
    def crear(self, nombre, tipo="gasto"):
        return self.cli.post("/api/categorias", json={"nombre": nombre, "tipo": tipo})

    def nombres(self, tipo="gasto"):
        return [c["nombre"] for c in self.cli.get("/api/categorias").get_json()[tipo]]

    def test_lista_completa_con_sin_clasificar_al_final(self):
        n = self.nombres()
        for esperada in ["Comida", "Mercado", "Ropa y calzado", "Cuidado personal", "Mascotas", "Regalos y familia",
                         "Ahorro y juntas", "Deudas"]:
            self.assertIn(esperada, n)
        self.assertEqual(n[-1], "Sin clasificar")
        self.assertNotIn("Otros", n)
        self.assertEqual(self.nombres("ingreso")[-1], "Sin clasificar")

    def test_crear_categoria_propia(self):
        r = self.crear("Fútbol con amigos")
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.get_json()["propia"])
        n = self.nombres()
        self.assertEqual((n[-2], n[-1]), ("Fútbol con amigos", "Sin clasificar"))
        self.assertEqual(self.nombres("ingreso").count("Fútbol con amigos"), 0)

    def test_se_puede_usar_en_movimientos_topes_y_fijos(self):
        self.crear("Fútbol")
        g = self.cli.post("/api/gastos", json={"concepto": "cancha", "monto": 20, "categoria": "Fútbol"})
        self.assertEqual((g.status_code, g.get_json()["categoria"]), (201, "Fútbol"))
        self.assertEqual(self.cli.put("/api/topes/F%C3%BAtbol", json={"monto": 50}).status_code, 200)
        f = self.cli.post("/api/fijos", json={"concepto": "liga", "monto": 10, "categoria": "Fútbol", "dia": 5})
        self.assertEqual(f.status_code, 201)
        self.assertIn("Fútbol", [t["categoria"] for t in self.cli.get("/api/topes").get_json()])

    def test_nombres_invalidos_o_repetidos(self):
        for nombre in ["", " ", "a", "x" * 31, "<b>hola</b>", "con/barra", "50%", "_raro"]:
            self.assertEqual(self.crear(nombre).status_code, 400, nombre)
        self.crear("Fútbol")
        for repetido in ["Fútbol", "futbol", "  FÚTBOL ", "comida", "Sin clasificar"]:
            self.assertEqual(self.crear(repetido).status_code, 400, repetido)
        self.assertEqual(self.crear("Fútbol", tipo="ingreso").status_code, 201)  # otro tipo: permitido
        self.assertEqual(self.crear("algo", tipo="otro").status_code, 400)

    def test_renombrar_actualiza_todo(self):
        self.crear("Fútbol")
        self.cli.post("/api/gastos", json={"concepto": "cancha", "monto": 20, "categoria": "Fútbol"})
        self.cli.put("/api/topes/F%C3%BAtbol", json={"monto": 50})
        r = self.cli.patch("/api/categorias/gasto/F%C3%BAtbol", json={"nombre": "Deporte"})
        self.assertEqual((r.status_code, r.get_json()["nombre"], r.get_json()["en_uso"]), (200, "Deporte", 1))
        self.assertEqual(self.cli.get("/api/movimientos").get_json()["items"][0]["categoria"], "Deporte")
        self.assertIn("Deporte", [t["categoria"] for t in self.cli.get("/api/topes").get_json() if t["tope_centimos"]])
        self.assertNotIn("Fútbol", self.nombres())

    def test_no_se_renombran_ni_borran_las_de_fabrica(self):
        self.assertEqual(self.cli.patch("/api/categorias/gasto/Comida", json={"nombre": "Alimentos"}).status_code, 400)
        self.assertEqual(self.cli.delete("/api/categorias/gasto/Comida").status_code, 400)

    def test_renombrar_a_un_nombre_repetido(self):
        self.crear("Fútbol")
        self.assertEqual(self.cli.patch("/api/categorias/gasto/F%C3%BAtbol", json={"nombre": "Comida"}).status_code, 400)
        self.assertEqual(self.cli.patch("/api/categorias/gasto/F%C3%BAtbol", json={"nombre": "futbol"}).status_code, 200)

    def test_borrar_solo_si_esta_vacia(self):
        self.crear("Fútbol")
        g = self.cli.post("/api/gastos", json={"concepto": "cancha", "monto": 20, "categoria": "Fútbol"}).get_json()
        r = self.cli.delete("/api/categorias/gasto/F%C3%BAtbol")
        self.assertEqual(r.status_code, 409)
        self.assertIn("1 movimiento", r.get_json()["error"])
        self.cli.delete(f"/api/gastos/{g['id']}")
        self.assertEqual(self.cli.delete("/api/categorias/gasto/F%C3%BAtbol").status_code, 204)
        self.assertNotIn("Fútbol", self.nombres())

    def test_borrar_limpia_tope_y_aprendizaje(self):
        self.crear("Fútbol")
        self.cli.put("/api/topes/F%C3%BAtbol", json={"monto": 50})
        self.cli.delete("/api/categorias/gasto/F%C3%BAtbol")
        self.assertEqual(self.cli.put("/api/topes/F%C3%BAtbol", json={"monto": 50}).status_code, 400)

    def test_sin_clasificar_no_admite_tope(self):
        self.assertEqual(self.cli.put("/api/topes/Sin%20clasificar", json={"monto": 50}).status_code, 400)

    def test_migracion_de_otros_a_sin_clasificar(self):
        with closing(db.conectar()) as con, con.cursor() as cur:
            cur.execute(
                "INSERT INTO gastos (fecha, texto, concepto, monto_centimos, categoria, categoria_auto, creado)"
                " VALUES ('2026-09-01', 'x 5', 'x', 500, 'Otros', 'Otros', '2026-09-01T00:00:00')"
            )
            cur.execute(
                "INSERT INTO ingresos (fecha, texto, concepto, monto_centimos, categoria, categoria_auto, creado)"
                " VALUES ('2026-09-01', 'y 5', 'y', 500, 'Otros ingresos', 'Otros ingresos', '2026-09-01T00:00:00')"
            )
            cur.execute("INSERT INTO topes (categoria, monto_centimos) VALUES ('Otros', 1000)")
            con.commit()
        db.iniciar()
        db.iniciar()  # repetir no rompe nada
        with closing(db.conectar()) as con, con.cursor() as cur:
            cur.execute("SELECT categoria, categoria_auto FROM gastos")
            fila = cur.fetchone()
            self.assertEqual((fila["categoria"], fila["categoria_auto"]), ("Sin clasificar", "Sin clasificar"))
            cur.execute("SELECT categoria FROM ingresos")
            self.assertEqual(cur.fetchone()["categoria"], "Sin clasificar")
            cur.execute("SELECT COUNT(*) AS n FROM topes")
            self.assertEqual(cur.fetchone()["n"], 0)


class TestAprendizaje(BaseLogueado):
    def test_lo_desconocido_avisa_que_hay_que_clasificar(self):
        (g,) = self.reg("cancha 20")["creados"]
        self.assertEqual((g["categoria"], g["categoria_dudosa"]), ("Sin clasificar", True))
        (c,) = self.reg("almuerzo 18")["creados"]
        self.assertFalse(c["categoria_dudosa"])

    def test_corregir_la_categoria_ensena_a_la_app(self):
        (g,) = self.reg("cancha 20")["creados"]
        self.cli.post("/api/categorias", json={"nombre": "Fútbol", "tipo": "gasto"})
        self.cli.patch(f"/api/gastos/{g['id']}", json={"categoria": "Fútbol"})
        (otro,) = self.reg("cancha 30")["creados"]
        self.assertEqual((otro["categoria"], otro["categoria_dudosa"]), ("Fútbol", False))

    def test_lo_aprendido_manda_sobre_las_reglas_de_fabrica(self):
        (g,) = self.reg("pollo 12")["creados"]
        self.assertEqual(g["categoria"], "Comida")
        self.cli.patch(f"/api/gastos/{g['id']}", json={"categoria": "Mercado"})
        (otro,) = self.reg("pollo 15")["creados"]
        self.assertEqual(otro["categoria"], "Mercado")
        self.assertEqual(otro["categoria_auto"], "Mercado")

    def test_lo_aprendido_tambien_vale_para_ingresos(self):
        (i,) = self.reg("+100 tanda")["creados"]
        self.assertEqual((i["categoria"], i["categoria_dudosa"]), ("Sin clasificar", True))
        self.cli.patch(f"/api/ingresos/{i['id']}", json={"categoria": "Ventas y cachuelos"})
        (otro,) = self.reg("+50 tanda")["creados"]
        self.assertEqual(otro["categoria"], "Ventas y cachuelos")

    def test_pasar_a_sin_clasificar_no_ensena_nada(self):
        (g,) = self.reg("pollo 12")["creados"]
        self.cli.patch(f"/api/gastos/{g['id']}", json={"categoria": "Sin clasificar"})
        (otro,) = self.reg("pollo 15")["creados"]
        self.assertEqual(otro["categoria"], "Comida")

    def test_sin_clasificar_se_recuerda_en_inicio(self):
        self.reg("cancha 20")
        self.reg("cancha 5")
        self.reg("almuerzo 18")
        i = self.cli.get("/api/inicio").get_json()["sin_clasificar"]
        self.assertEqual((i["n"], i["total_centimos"]), (2, 2500))

    def test_lo_que_pasa_en_el_dialogo_manual_tambien_ensena(self):
        self.cli.post("/api/categorias", json={"nombre": "Fútbol", "tipo": "gasto"})
        self.cli.post("/api/gastos", json={"concepto": "cancha", "monto": 20, "categoria": "Fútbol"})
        (otro,) = self.reg("cancha 30")["creados"]
        self.assertEqual(otro["categoria"], "Fútbol")


class TestSugerir(BaseLogueado):
    def sugerir(self, concepto, tipo="gasto"):
        return self.cli.get("/api/sugerir", query_string={"tipo": tipo, "concepto": concepto})

    def test_sugiere_segun_el_detalle(self):
        self.assertEqual(self.sugerir("almuerzo con Juan").get_json()["categoria"], "Comida")
        self.assertEqual(self.sugerir("sueldo", "ingreso").get_json()["categoria"], "Sueldo")

    def test_desconocido_o_vacio_no_sugiere(self):
        self.assertIsNone(self.sugerir("xyz").get_json()["categoria"])
        self.assertIsNone(self.sugerir("   ").get_json()["categoria"])
        self.assertIsNone(self.cli.get("/api/sugerir").get_json()["categoria"])

    def test_usa_lo_aprendido(self):
        self.cli.post("/api/categorias", json={"nombre": "Fútbol", "tipo": "gasto"})
        self.cli.post("/api/gastos", json={"concepto": "cancha", "monto": 20, "categoria": "Fútbol"})
        self.assertEqual(self.sugerir("cancha sintética").get_json()["categoria"], "Fútbol")

    def test_tipo_invalido_y_sin_sesion(self):
        self.assertEqual(self.sugerir("taxi", "otro").status_code, 400)
        self.cli.post("/logout")
        self.assertEqual(self.sugerir("taxi").status_code, 401)


class TestRegistrarConOpciones(BaseLogueado):
    def registrar(self, texto, **extra):
        return self.cli.post("/api/registrar", json={"texto": texto, **extra})

    def test_fecha_elegida_en_pantalla(self):
        anteayer = (tiempo.hoy() - timedelta(days=2)).strftime("%Y-%m-%d")
        r = self.registrar("taxi 8", fecha=anteayer)
        self.assertEqual(r.get_json()["creados"][0]["fecha"], anteayer)

    def test_la_fecha_del_texto_gana_sobre_la_elegida(self):
        hoy = db.hoy()
        r = self.registrar("ayer taxi 8", fecha=hoy)
        ayer = (tiempo.hoy() - timedelta(days=1)).strftime("%Y-%m-%d")
        self.assertEqual(r.get_json()["creados"][0]["fecha"], ayer)

    def test_la_fecha_elegida_vale_para_todos_los_de_la_linea(self):
        anteayer = (tiempo.hoy() - timedelta(days=2)).strftime("%Y-%m-%d")
        r = self.registrar("taxi 8, menú 12", fecha=anteayer)
        self.assertEqual({c["fecha"] for c in r.get_json()["creados"]}, {anteayer})

    def test_fecha_invalida(self):
        self.assertEqual(self.registrar("taxi 8", fecha="2999-01-01").status_code, 400)
        self.assertEqual(self.registrar("taxi 8", fecha="ayer").status_code, 400)

    def test_categoria_elegida_en_pantalla(self):
        r = self.registrar("cancha 20", categoria="Ocio")
        (g,) = r.get_json()["creados"]
        self.assertEqual((g["categoria"], g["categoria_dudosa"], g["categoria_auto"]), ("Ocio", False, "Sin clasificar"))

    def test_categoria_elegida_se_aprende(self):
        self.registrar("cancha 20", categoria="Ocio")
        (otro,) = self.reg("cancha 30")["creados"]
        self.assertEqual((otro["categoria"], otro["categoria_dudosa"]), ("Ocio", False))

    def test_categoria_de_ingreso_solo_se_aplica_a_ingresos(self):
        r = self.registrar("sueldo 800, taxi 8", categoria="Sueldo")
        gasto = next(c for c in r.get_json()["creados"] if c["tipo"] == "gasto")
        ingreso = next(c for c in r.get_json()["creados"] if c["tipo"] == "ingreso")
        self.assertEqual((ingreso["categoria"], gasto["categoria"]), ("Sueldo", "Transporte"))

    def test_categoria_inexistente(self):
        self.assertEqual(self.registrar("taxi 8", categoria="Inventada").status_code, 400)
        self.assertEqual(self.registrar("taxi 8", categoria=123).status_code, 400)

    def test_sin_opciones_todo_sigue_igual(self):
        (g,) = self.registrar("almuerzo 18", categoria="", fecha="").get_json()["creados"]
        self.assertEqual((g["categoria"], g["fecha"]), ("Comida", db.hoy()))


class TestExportar(BaseLogueado):
    def test_csv(self):
        self.reg("almuerzo 18")
        self.reg("sueldo 800")
        r = self.cli.get("/exportar.csv")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r.headers["Content-Type"])
        self.assertIn("attachment", r.headers["Content-Disposition"])
        texto = r.get_data(as_text=True)
        self.assertTrue(texto.startswith("﻿tipo,fecha,concepto,categoria,monto_soles,texto_original"))
        self.assertIn("gasto,", texto)
        self.assertIn("ingreso,", texto)
        self.assertIn("18.00", texto)
        self.assertIn("800.00", texto)

    def test_no_permite_formulas_en_excel(self):
        self.reg("=1+1 taxi 5")
        self.assertIn("'=1+1 taxi", self.cli.get("/exportar.csv").get_data(as_text=True))


class TestHistorial(BaseLogueado):
    def historial(self):
        return self.cli.get("/api/historial").get_json()

    def test_requiere_login(self):
        self.cli.post("/logout")
        self.assertEqual(self.cli.get("/api/historial").status_code, 401)

    def test_pagina_vacia(self):
        r = self.cli.get("/historial")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Todavía no se ha borrado nada".encode(), r.data)
        self.assertEqual(self.historial(), [])

    def test_borrar_gasto_queda_en_el_historial(self):
        g = self.reg("almuerzo 18")["creados"][0]
        self.cli.delete(f"/api/gastos/{g['id']}")
        (h,) = self.historial()
        self.assertEqual((h["tipo"], h["descripcion"], h["detalle"], h["monto_centimos"], h["fecha"]),
                         ("gasto", "almuerzo", "Comida", 1800, db.hoy()))
        self.assertIsNotNone(h["borrado_en"])

    def test_borrar_ingreso_queda_en_el_historial(self):
        i = self.reg("sueldo 800")["creados"][0]
        self.cli.delete(f"/api/ingresos/{i['id']}")
        (h,) = self.historial()
        self.assertEqual((h["tipo"], h["descripcion"], h["monto_centimos"]), ("ingreso", "sueldo", 80000))

    def test_borrar_gasto_fijo_queda_en_el_historial(self):
        f = self.cli.post("/api/fijos", json={"concepto": "alquiler", "monto": 500, "categoria": "Hogar", "dia": 5}).get_json()
        self.cli.delete(f"/api/fijos/{f['id']}")
        (h,) = self.historial()
        self.assertEqual((h["tipo"], h["descripcion"], h["detalle"], h["monto_centimos"]), ("fijo", "alquiler", "Hogar", 50000))

    def test_borrar_deuda_queda_en_el_historial(self):
        d = self.cli.post("/api/deudas", json={"persona": "Juan", "monto": 25, "tipo": "me_deben"}).get_json()
        self.cli.delete(f"/api/deudas/{d['id']}")
        (h,) = self.historial()
        self.assertEqual((h["tipo"], h["descripcion"], h["detalle"], h["monto_centimos"]), ("deuda", "Juan", "Te debía", 2500))

    def test_borrar_categoria_queda_en_el_historial(self):
        self.cli.post("/api/categorias", json={"nombre": "Fútbol", "tipo": "gasto"})
        self.cli.delete("/api/categorias/gasto/F%C3%BAtbol")
        (h,) = self.historial()
        self.assertEqual((h["tipo"], h["descripcion"], h["monto_centimos"]), ("categoria", "Fútbol", None))

    def test_orden_mas_reciente_primero(self):
        g1 = self.reg("almuerzo 18")["creados"][0]
        g2 = self.reg("taxi 8")["creados"][0]
        self.cli.delete(f"/api/gastos/{g1['id']}")
        self.cli.delete(f"/api/gastos/{g2['id']}")
        h = self.historial()
        self.assertEqual([x["descripcion"] for x in h], ["taxi", "almuerzo"])

    def test_borrar_uno_inexistente_no_deja_rastro(self):
        self.cli.delete("/api/gastos/9999")
        self.assertEqual(self.historial(), [])


if __name__ == "__main__":
    unittest.main()
