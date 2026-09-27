import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date  # noqa: E402

from parseo import ErrorParser, parsear, parsear_varios, tokens_significativos  # noqa: E402


class TestMonto(unittest.TestCase):
    def test_entero(self):
        self.assertEqual(parsear("almuerzo 18").monto_centimos, 1800)

    def test_monto_primero(self):
        self.assertEqual(parsear("18 almuerzo").monto_centimos, 1800)

    def test_decimal_punto_y_coma(self):
        self.assertEqual(parsear("taxi 12.5").monto_centimos, 1250)
        self.assertEqual(parsear("taxi 12,50").monto_centimos, 1250)

    def test_prefijo_soles(self):
        self.assertEqual(parsear("menú S/ 12").monto_centimos, 1200)
        self.assertEqual(parsear("menú s/12.50").monto_centimos, 1250)

    def test_prefijo_gana_sobre_otros_numeros(self):
        g = parsear("2 menús s/ 24")
        self.assertEqual(g.monto_centimos, 2400)
        self.assertEqual(g.concepto, "2 menús")

    def test_miles(self):
        self.assertEqual(parsear("alquiler 1,250").monto_centimos, 125000)
        self.assertEqual(parsear("alquiler 1,250.50").monto_centimos, 125050)

    def test_sin_monto(self):
        with self.assertRaises(ErrorParser):
            parsear("almuerzo")

    def test_vacio(self):
        with self.assertRaises(ErrorParser):
            parsear("   ")

    def test_cero(self):
        with self.assertRaises(ErrorParser):
            parsear("almuerzo 0")


class TestConcepto(unittest.TestCase):
    def test_concepto_sin_monto(self):
        self.assertEqual(parsear("almuerzo 18").concepto, "almuerzo")
        self.assertEqual(parsear("pollo a la brasa 35 soles").concepto, "pollo a la brasa")

    def test_solo_monto(self):
        self.assertEqual(parsear("15").concepto, "Sin concepto")


class TestCategorias(unittest.TestCase):
    def assertCategoria(self, texto, esperada):
        self.assertEqual(parsear(texto).categoria, esperada, texto)

    def test_jerga_peruana(self):
        self.assertCategoria("combi 1.50", "Transporte")
        self.assertCategoria("menú 12", "Comida")
        self.assertCategoria("menu 12", "Comida")
        self.assertCategoria("chifa 35", "Comida")
        self.assertCategoria("chelas 20", "Ocio")
        self.assertCategoria("recarga entel 10", "Servicios")
        self.assertCategoria("inkafarma 45", "Salud")
        self.assertCategoria("wong 120", "Mercado")

    def test_delivery_gana_sobre_comida(self):
        self.assertCategoria("delivery pollo 30", "Delivery")
        self.assertCategoria("rappi 28", "Delivery")

    def test_plurales(self):
        self.assertCategoria("2 menús 24", "Comida")
        self.assertCategoria("buses 3", "Transporte")

    def test_palabra_completa(self):
        # "gas" (servicio) no debe activarse dentro de "gasolina"
        self.assertCategoria("gasolina 60", "Transporte")
        # "metro" (supermercado) no debe activarse dentro de "metropolitano"
        self.assertCategoria("metropolitano 2.50", "Transporte")
        self.assertCategoria("metro 85", "Mercado")

    def test_pollo_crudo_es_mercado(self):
        self.assertCategoria("pollo crudo 20", "Mercado")

    def test_desconocido_queda_sin_clasificar_y_avisa(self):
        g = parsear("xyz 80")
        self.assertEqual((g.categoria, g.dudosa), ("Sin clasificar", True))
        self.assertFalse(parsear("almuerzo 18").dudosa)

    def test_categorias_nuevas(self):
        self.assertCategoria("regalo mamá 80", "Regalos y familia")
        self.assertCategoria("zapatillas 120", "Ropa y calzado")
        self.assertCategoria("corte de pelo 15", "Cuidado personal")
        self.assertCategoria("veterinario 60", "Mascotas")
        self.assertCategoria("comida de perro 40", "Mascotas")
        self.assertCategoria("multa 90", "Trámites y multas")
        self.assertCategoria("junta 100", "Ahorro y juntas")


HOY = date(2026, 9, 26)


class TestFechas(unittest.TestCase):
    def fecha(self, texto):
        return parsear(texto, HOY).fecha

    def test_sin_fecha_es_none(self):
        self.assertIsNone(self.fecha("almuerzo 18"))

    def test_hoy_ayer_anteayer(self):
        self.assertEqual(self.fecha("hoy almuerzo 18"), HOY)
        self.assertEqual(self.fecha("ayer taxi 8"), date(2026, 9, 25))
        self.assertEqual(self.fecha("taxi 8 ayer"), date(2026, 9, 25))
        self.assertEqual(self.fecha("anteayer taxi 8"), date(2026, 9, 24))
        self.assertEqual(self.fecha("antes de ayer taxi 8"), date(2026, 9, 24))

    def test_hace_n_dias(self):
        self.assertEqual(self.fecha("menú 12 hace 3 días"), date(2026, 9, 23))

    def test_el_dia_n(self):
        self.assertEqual(self.fecha("menú 12 el 15"), date(2026, 9, 15))
        self.assertEqual(self.fecha("menú 12 el día 3"), date(2026, 9, 3))

    def test_el_dia_mayor_a_hoy_es_mes_anterior(self):
        self.assertEqual(self.fecha("menú 12 el 28"), date(2026, 8, 28))

    def test_dia_mes(self):
        self.assertEqual(self.fecha("menú 12 15/09"), date(2026, 9, 15))
        self.assertEqual(self.fecha("menú 12 el 5/9"), date(2026, 9, 5))
        self.assertEqual(self.fecha("menú 12 15/09/2025"), date(2025, 9, 15))

    def test_dia_mes_futuro_es_del_anio_pasado(self):
        self.assertEqual(self.fecha("menú 12 30/12"), date(2025, 12, 30))

    def test_media_porcion_no_es_fecha(self):
        g = parsear("1/2 pollo 35", HOY)
        self.assertIsNone(g.fecha)
        self.assertEqual(g.monto_centimos, 3500)

    def test_la_fecha_no_se_confunde_con_el_monto(self):
        g = parsear("ayer almuerzo 18", HOY)
        self.assertEqual((g.monto_centimos, g.concepto), (1800, "almuerzo"))
        g = parsear("almuerzo el 15 18", HOY)
        self.assertEqual((g.monto_centimos, g.concepto, g.fecha), (1800, "almuerzo", date(2026, 9, 15)))

    def test_fecha_inexistente(self):
        with self.assertRaises(ErrorParser):
            parsear("menú 12 31/02", HOY)
        with self.assertRaises(ErrorParser):
            parsear("menú 12 el 0", HOY)


class TestTipos(unittest.TestCase):
    def test_ingresos_por_palabra(self):
        for texto, categoria in [
            ("sueldo 800", "Sueldo"),
            ("cobré quincena 450", "Sueldo"),
            ("venta de dulces 35", "Ventas y cachuelos"),
            ("propina 10", "Ventas y cachuelos"),
            ("cachuelo 60", "Ventas y cachuelos"),
            ("me pagaron 120", "Sin clasificar"),
        ]:
            g = parsear(texto, HOY)
            self.assertEqual((g.tipo, g.categoria), ("ingreso", categoria), texto)

    def test_ingreso_con_signo_mas(self):
        g = parsear("+50 regalo de mi tía", HOY)
        self.assertEqual((g.tipo, g.monto_centimos, g.categoria), ("ingreso", 5000, "Regalos y apoyo"))

    def test_gasto_por_defecto(self):
        self.assertEqual(parsear("almuerzo 18", HOY).tipo, "gasto")

    def test_prestamo_a_persona(self):
        g = parsear("le presté 25 a Juan", HOY)
        self.assertEqual((g.tipo, g.persona, g.monto_centimos, g.categoria), ("me_deben", "Juan", 2500, "Deudas"))
        g = parsear("presté 20 a mi hermano", HOY)
        self.assertEqual((g.tipo, g.persona), ("me_deben", "mi hermano"))

    def test_deudas_que_debo(self):
        g = parsear("debo 30 a Pedro", HOY)
        self.assertEqual((g.tipo, g.persona), ("debo", "Pedro"))
        g = parsear("fiado bodega 15", HOY)
        self.assertEqual((g.tipo, g.persona, g.monto_centimos), ("debo", "bodega", 1500))

    def test_pago_de_cuota_es_gasto_en_deudas(self):
        g = parsear("cuota tarjeta 150", HOY)
        self.assertEqual((g.tipo, g.categoria), ("gasto", "Deudas"))


class TestAprendizaje(unittest.TestCase):
    def test_tokens_significativos(self):
        self.assertEqual(tokens_significativos("Regalo de mamá 80"), ["regalo", "mama"])
        self.assertEqual(tokens_significativos("pollo a la brasa"), ["pollo", "brasa"])
        self.assertEqual(tokens_significativos("12 de 5"), [])

    def test_lo_aprendido_manda_sobre_las_reglas_de_fabrica(self):
        aprendida = lambda tipo, tokens: "Mi negocio" if "pollo" in tokens else None
        g = parsear("pollo 20", HOY, aprendida)
        self.assertEqual((g.categoria, g.dudosa), ("Mi negocio", False))

    def test_lo_aprendido_evita_preguntar(self):
        aprendida = lambda tipo, tokens: "Fútbol" if "xyz" in tokens else None
        g = parsear("xyz 30", HOY, aprendida)
        self.assertEqual((g.categoria, g.dudosa), ("Fútbol", False))

    def test_se_pregunta_el_tipo_correcto(self):
        vistos = []
        parsear("sueldo 100", HOY, lambda tipo, tokens: vistos.append(tipo))
        parsear("taxi 5", HOY, lambda tipo, tokens: vistos.append(tipo))
        self.assertEqual(vistos, ["ingreso", "gasto"])


class TestVarios(unittest.TestCase):
    def test_por_coma(self):
        ms = parsear_varios("menú 12, taxi 8", HOY)
        self.assertEqual([(m.concepto, m.monto_centimos) for m in ms], [("menú", 1200), ("taxi", 800)])

    def test_por_y_solo_si_ambos_lados_tienen_monto(self):
        self.assertEqual(len(parsear_varios("menú 12 y taxi 8", HOY)), 2)
        ms = parsear_varios("arroz y pollo 15", HOY)
        self.assertEqual((len(ms), ms[0].concepto), (1, "arroz y pollo"))

    def test_miles_no_dividen(self):
        ms = parsear_varios("alquiler 1,250", HOY)
        self.assertEqual((len(ms), ms[0].monto_centimos), (1, 125000))

    def test_la_fecha_se_comparte(self):
        ms = parsear_varios("menú 12 y taxi 8 ayer", HOY)
        self.assertEqual({m.fecha for m in ms}, {date(2026, 9, 25)})

    def test_mezcla_de_tipos(self):
        ms = parsear_varios("sueldo 800, menú 12", HOY)
        self.assertEqual([m.tipo for m in ms], ["ingreso", "gasto"])

    def test_un_error_invalida_todo(self):
        with self.assertRaises(ErrorParser):
            parsear_varios("menú 12, taxi", HOY)

    def test_limite(self):
        with self.assertRaises(ErrorParser):
            parsear_varios(", ".join(["taxi 1"] * 11), HOY)

    def test_vacio(self):
        with self.assertRaises(ErrorParser):
            parsear_varios("  ", HOY)


if __name__ == "__main__":
    unittest.main()
