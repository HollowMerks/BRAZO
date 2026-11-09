import math
import unittest

from motor.cinematica import base_en_plano, eslabon, holgura, inversa, puntos
from motor.config import Config


class Cinematica(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()

    def test_eje_a_eje_coincide_con_lo_medido(self):
        largo, desvio = eslabon(self.cfg)
        # Agujeros de la pieza gris en el modelo 3D (200 de eje a eje) menos el corte de ~50 mm
        self.assertAlmostEqual(largo, 151.9, delta=0.1)
        self.assertGreater(desvio, 0)

    def test_tramo_recto_vertical_codo_adelante(self):
        p = puntos(self.cfg, 90, -90)
        c = self.cfg
        self.assertAlmostEqual(p["doblez"][0], 0, places=6)
        self.assertAlmostEqual(p["doblez"][1], c.altura_hombro + c.brazo_recto)
        # El tramo inclinado lleva el codo hacia adelante
        self.assertAlmostEqual(p["codo"][0], c.brazo_inclinado * math.sin(math.radians(c.brazo_angulo)))
        # Codo -90: antebrazo horizontal hacia adelante
        self.assertAlmostEqual(p["punta"][1], p["codo"][1])
        self.assertAlmostEqual(p["punta"][0], p["codo"][0] + c.largo_antebrazo)

    def test_tramo_recto_horizontal(self):
        p = puntos(self.cfg, 0, 0)
        c = self.cfg
        a = math.radians(c.brazo_angulo)
        self.assertAlmostEqual(p["codo"][0], c.brazo_recto + c.brazo_inclinado * math.cos(a))
        self.assertAlmostEqual(p["codo"][1], c.altura_hombro - c.brazo_inclinado * math.sin(a))

    def test_inversa_recupera_los_angulos(self):
        for hombro, codo in ((90, -91), (60, -40), (110, -130), (45, -25), (120, -150)):
            x, y = puntos(self.cfg, hombro, codo)["punta"]
            h, c = inversa(self.cfg, x, y, codo)
            self.assertAlmostEqual(h, hombro, places=6)
            self.assertAlmostEqual(c, codo, places=6)

    def test_inversa_fuera_de_alcance(self):
        self.assertIsNone(inversa(self.cfg, 1000, 1000, -30))

    def test_reposo_no_toca_nada(self):
        self.assertGreater(holgura(self.cfg, self.cfg.reposo_hombro, self.cfg.reposo_codo).mm, 0)

    def test_antebrazo_hacia_abajo_toca_la_mesa(self):
        hg = holgura(self.cfg, 30, -100)
        self.assertLess(hg.mm, 0)
        self.assertIn("mesa", hg.donde)

    def test_choca_con_la_caja_solo_si_queda_debajo(self):
        # Torreta girada hacia la caja y antebrazo plegado con el brazo inclinado: la punta baja sobre ella
        hg = holgura(Config(giro=180), 50, -130)
        self.assertLess(hg.mm, 0)
        self.assertIn("base", hg.donde)
        # Con la torreta girada 90°, bajo el brazo solo queda el semicírculo y la punta cae fuera
        girado = Config(giro=90)
        self.assertLess(base_en_plano(girado)[1], puntos(girado, 50, -130)["punta"][0])
        self.assertGreater(holgura(girado, 50, -130).mm, 0)

    def test_antebrazo_volviendo_sobre_la_base(self):
        # Con giro 0 lo largo de la caja queda detrás; plegado de más, el antebrazo baja sobre el semicírculo
        hg = holgura(Config(garra_montada=False), 30, -175)
        self.assertLess(hg.mm, 0)
        self.assertIn("base", hg.donde)

    def test_margen_y_grosor_cuentan(self):
        cfg = Config(margen=0, grosor_antebrazo=0, garra_montada=False)
        # Buscar un codo con la punta justo a 10 mm sobre la mesa
        h = 15
        p = puntos(cfg, h, 0)
        a = math.degrees(math.asin((10 - p["codo"][1]) / cfg.largo_antebrazo)) - h
        self.assertAlmostEqual(puntos(cfg, h, a)["punta"][1], 10, places=6)
        self.assertAlmostEqual(holgura(cfg, h, a).mm, 10, places=6)
        self.assertAlmostEqual(holgura(Config(margen=15, grosor_antebrazo=0, garra_montada=False), h, a).mm, -5, places=6)


if __name__ == "__main__":
    unittest.main()
