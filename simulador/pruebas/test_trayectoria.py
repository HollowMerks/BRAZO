import time
import unittest

from motor.cinematica import holgura
from motor.config import Articulacion, Config
from motor.trayectoria import PASO, _quintica, _valor, planificar


def _derivada(c, t, h=1e-5):
    return (_valor(c, t + h) - _valor(c, t - h)) / (2 * h)


class Quintica(unittest.TestCase):
    def test_condiciones_de_borde(self):
        c = _quintica(10, 5, 0, 50, 2.0)
        self.assertAlmostEqual(_valor(c, 0), 10)
        self.assertAlmostEqual(_valor(c, 2.0), 50)
        self.assertAlmostEqual(_derivada(c, 1e-4), 5, places=2)
        self.assertAlmostEqual(_derivada(c, 2.0 - 1e-4), 0, places=2)


class Planificar(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()
        self.reposo = [self.cfg.reposo_hombro, self.cfg.reposo_codo]

    def _comprobar_seguro(self, plan):
        for h, c in zip(plan.hombro, plan.codo):
            self.assertGreaterEqual(holgura(self.cfg, h, c).mm, -1e-6)
            self.assertTrue(self.cfg.codo.minimo - 1e-6 <= c <= self.cfg.codo.maximo + 1e-6)
        for serie, art in ((plan.hombro, self.cfg.hombro), (plan.codo, self.cfg.codo)):
            mayor = max(abs(b - a) for a, b in zip(serie, serie[1:])) / PASO
            self.assertLessEqual(mayor, art.vmax * 1.05)

    def test_movimiento_libre_llega_exacto_y_coordinado(self):
        plan = planificar(self.cfg, self.reposo, [0, 0], (60, -60))
        self.assertTrue(plan.valido, plan.motivo)
        self.assertEqual(len(plan.hombro), len(plan.codo))
        self.assertAlmostEqual(plan.hombro[-1], 60)
        self.assertAlmostEqual(plan.codo[-1], -60)
        self.assertEqual(plan.corregido, 0)
        self._comprobar_seguro(plan)
        # Coordinado: las dos articulaciones se mueven durante todo el plan
        mitad = len(plan.hombro) // 2
        self.assertNotAlmostEqual(plan.hombro[mitad], plan.hombro[0])
        self.assertNotAlmostEqual(plan.codo[mitad], plan.codo[0])

    def test_bajar_con_el_antebrazo_colgando_flexiona_el_codo(self):
        plan = planificar(self.cfg, self.reposo, [0, 0], (30, -115))
        self.assertTrue(plan.valido, plan.motivo)
        self.assertGreater(plan.corregido, 5)
        self.assertGreater(plan.codo[-1], -115)  # terminó más flexionado de lo pedido
        self._comprobar_seguro(plan)

    def test_sin_margen_de_codo_se_rechaza(self):
        cfg = Config(codo=Articulacion(-120, -110, 40, 80), reposo_codo=-115)
        plan = planificar(cfg, [90, -115], [0, 0], (30, -115))
        self.assertFalse(plan.valido)
        self.assertIn("contra la mesa", plan.motivo)

    def test_destino_fuera_de_limites(self):
        plan = planificar(self.cfg, self.reposo, [0, 0], (170, -40))
        self.assertFalse(plan.valido)
        self.assertIn("límites", plan.motivo)

    def test_desde_movimiento_no_salta(self):
        plan = planificar(self.cfg, self.reposo, [10, -10], (50, -60))
        self.assertTrue(plan.valido, plan.motivo)
        v0 = (plan.hombro[1] - plan.hombro[0]) / PASO
        self.assertAlmostEqual(v0, 10, delta=1.0)

    def test_planificar_es_rapido(self):
        inicio = time.perf_counter()
        planificar(self.cfg, self.reposo, [0, 0], (30, -115))
        self.assertLess(time.perf_counter() - inicio, 0.25)


if __name__ == "__main__":
    unittest.main()
