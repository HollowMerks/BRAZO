import tempfile
import unittest
from pathlib import Path

from motor.calibracion import Calibracion, ajustar, us_para
from motor.nano import leer_informe


class Ajuste(unittest.TestCase):
    def test_recta_exacta(self):
        a = ajustar([[1000, 40], [1500, 90], [2000, 140]])
        self.assertAlmostEqual(a["pendiente"], 0.1)
        self.assertAlmostEqual(a["error_max"], 0, places=9)
        self.assertAlmostEqual(us_para(a, 90), 1500)

    def test_hombro_espejado_tiene_pendiente_negativa(self):
        a = ajustar([[1000, 140], [2000, 40]])
        self.assertLess(a["pendiente"], 0)
        self.assertAlmostEqual(us_para(a, 90), 1500)

    def test_un_solo_pulso_no_alcanza(self):
        self.assertIsNone(ajustar([[1500, 90], [1500, 91]]))

    def test_error_maximo_detecta_curvatura(self):
        a = ajustar([[1000, 40], [1500, 95], [2000, 140]])
        self.assertGreater(a["error_max"], 2)


class Espejo(unittest.TestCase):
    def test_derecho_se_deduce_del_izquierdo(self):
        with tempfile.TemporaryDirectory() as d:
            c = Calibracion(Path(d) / "c.json")
            c.agregar("hombro_izq", 1272, 70)
            c.agregar("hombro_izq", 1472, 90)
            c.agregar("hombro_izq", 1672, 110)
            der = c.ajuste("hombro_der")
            self.assertTrue(der["espejo"])
            # Mismo ángulo → pulsos simétricos alrededor de 1472
            for angulo in (70, 90, 110):
                self.assertAlmostEqual(us_para(der, angulo) + us_para(c.ajuste("hombro_izq"), angulo), 2944)

    def test_puntos_propios_del_derecho_mandan(self):
        with tempfile.TemporaryDirectory() as d:
            c = Calibracion(Path(d) / "c.json")
            c.agregar("hombro_izq", 1272, 70)
            c.agregar("hombro_izq", 1672, 110)
            c.agregar("hombro_der", 1300, 110)
            c.agregar("hombro_der", 1700, 70)
            self.assertNotIn("espejo", c.ajuste("hombro_der"))


class Archivo(unittest.TestCase):
    def test_guardar_reemplazar_y_borrar(self):
        with tempfile.TemporaryDirectory() as d:
            ruta = Path(d) / "calibracion.json"
            c = Calibracion(ruta)
            c.agregar("codo", 1500, -90)
            c.agregar("codo", 1502, -91)  # mismo pulso: reemplaza
            c.agregar("codo", 1800, -60)
            self.assertEqual(Calibracion(ruta).puntos["codo"], [[1502, -91], [1800, -60]])
            c.borrar("codo", 0)
            self.assertEqual(Calibracion(ruta).puntos["codo"], [[1800, -60]])


class Informe(unittest.TestCase):
    def test_informe_valido(self):
        s = leer_informe("E 1 1472 0 1500 1 1300 0 1500")
        self.assertEqual(s[0], {"activo": True, "us": 1472})
        self.assertEqual(s[1], {"activo": False, "us": 1500})

    def test_lineas_ajenas(self):
        self.assertIsNone(leer_informe("LISTO BrazoNano 1"))
        self.assertIsNone(leer_informe("E 1 2"))


if __name__ == "__main__":
    unittest.main()
