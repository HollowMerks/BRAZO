import unittest

from motor.cinematica import base_en_plano
from motor.config import Config


class ConfigBase(unittest.TestCase):
    def test_valores_por_defecto_son_validos(self):
        self.assertEqual(Config().errores(), [])

    def test_caja_imposible_es_error(self):
        self.assertTrue(Config(caja_largo=40).errores())
        self.assertTrue(Config(giro=200).errores())

    def test_medidas_viejas_se_ignoran(self):
        # config.json de antes del modelo 3D: base_adelante/base_atras ya no existen
        c = Config.desde_dict({"base_adelante": 127, "base_atras": 93, "margen": 10})
        self.assertEqual(c.margen, 10)
        self.assertEqual(c.caja_largo, Config().caja_largo)


class BaseBajoElBrazo(unittest.TestCase):
    def test_como_esta_armado(self):
        # Giro 0 (foto del 30/10): el brazo mira al extremo redondo y lo largo de la caja queda detrás
        c = Config(giro=0)
        r = c.caja_ancho / 2
        desde, hasta = base_en_plano(c)
        self.assertAlmostEqual(desde, -(c.caja_largo - r - c.hombro_atras_giro), places=6)
        self.assertAlmostEqual(hasta, r + c.hombro_atras_giro, places=6)

    def test_de_costado_solo_queda_el_semicirculo(self):
        c = Config(giro=90)
        r = c.caja_ancho / 2
        desde, hasta = base_en_plano(c)
        self.assertAlmostEqual(desde, -(r - c.hombro_atras_giro), places=6)
        self.assertAlmostEqual(hasta, r + c.hombro_atras_giro, places=6)

    def test_vuelta_entera_la_caja_queda_delante(self):
        c = Config(giro=180)
        r = c.caja_ancho / 2
        desde, hasta = base_en_plano(c)
        self.assertAlmostEqual(desde, -(r - c.hombro_atras_giro), places=6)
        self.assertAlmostEqual(hasta, c.caja_largo - r + c.hombro_atras_giro, places=6)

    def test_simetrico(self):
        for g in (20, 45, 70, 120):
            a, b = base_en_plano(Config(giro=g)), base_en_plano(Config(giro=-g))
            self.assertAlmostEqual(a[0], b[0], places=6)
            self.assertAlmostEqual(a[1], b[1], places=6)


if __name__ == "__main__":
    unittest.main()
