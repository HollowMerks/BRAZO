import math
import unittest

from motor.cinematica import holgura, puntos, radios_mano
from motor.config import Config
from motor.control import Controlador
from motor.trayectoria import PASO


class Geometria(unittest.TestCase):
    def test_la_mano_sigue_al_antebrazo_desde_la_muneca(self):
        cfg = Config(muneca=0)
        p = puntos(cfg, 90, -90)  # antebrazo horizontal hacia adelante
        self.assertAlmostEqual(p["dedos"][1], p["punta"][1])
        self.assertAlmostEqual(p["dedos"][0] - p["punta"][0], cfg.mano_largo)
        self.assertAlmostEqual(p["palma"][0] - p["punta"][0], cfg.mano_palma)

    def test_la_muneca_dobla_la_mano_hacia_arriba(self):
        cfg = Config(muneca=90)
        p = puntos(cfg, 90, -90)
        self.assertAlmostEqual(p["dedos"][0], p["punta"][0], places=6)
        self.assertAlmostEqual(p["dedos"][1] - p["punta"][1], cfg.mano_largo)

    def test_sin_garra_no_hay_mano(self):
        self.assertNotIn("dedos", puntos(Config(garra_montada=False), 90, -90))

    def test_girada_90_el_ancho_de_los_dedos_queda_en_el_plano(self):
        recta = radios_mano(Config(giro_muneca=0, garra=0))
        girada = radios_mano(Config(giro_muneca=90, garra=0))
        abierta = radios_mano(Config(giro_muneca=90, garra=100))
        self.assertLess(recta[1], girada[1])
        self.assertLess(girada[1], abierta[1])
        self.assertAlmostEqual(abierta[1], Config().garra_ancho_abierta)


class Choques(unittest.TestCase):
    def test_pose_de_inicio_con_la_muneca_doblada_es_valida(self):
        cfg = Config()
        self.assertGreater(holgura(cfg, cfg.reposo_hombro, cfg.reposo_codo).mm, 0)
        # Brazo plegado y muñeca recta: los dedos quedarían bajo la mesa
        self.assertLess(holgura(Config(muneca=0), 90, -180).mm, 0)

    def test_los_dedos_apuntando_a_la_mesa_chocan_antes_que_el_antebrazo(self):
        sin = Config(garra_montada=False)
        con = Config(muneca=-60)
        self.assertGreater(holgura(sin, 45, -70).mm, 0)
        hg = holgura(con, 45, -70)
        self.assertLess(hg.mm, 0)
        self.assertIn("garra", hg.donde)


class Control(unittest.TestCase):
    def setUp(self):
        self.ctl = Controlador(Config())
        self.ctl.pos = [90, -91]  # antebrazo horizontal, la mano libre

    def _pasos(self, n):
        for _ in range(n):
            self.ctl._paso(PASO)

    def test_cada_articulacion_llega_a_su_objetivo(self):
        self.ctl.mover_auxiliar("muneca", 30)
        self.ctl.mover_auxiliar("giro_muneca", -45)
        self.ctl.mover_auxiliar("garra", 100)
        self._pasos(300)
        self.assertEqual((self.ctl.cfg.muneca, self.ctl.cfg.giro_muneca, self.ctl.cfg.garra), (30, -45, 100))

    def test_no_salen_de_sus_limites(self):
        self.assertEqual(self.ctl.mover_auxiliar("muneca", 500), 90)
        self.assertEqual(self.ctl.mover_auxiliar("garra", -20), 0)

    def test_doblar_la_muneca_hacia_la_mesa_se_detiene(self):
        ctl = Controlador(Config(muneca=0))
        ctl.pos = [45, -70]
        self.assertGreater(holgura(ctl.cfg, *ctl.pos).mm, 0)
        ctl.mover_auxiliar("muneca", -90)
        for _ in range(500):
            ctl._paso(PASO)
            self.assertGreaterEqual(holgura(ctl.cfg, *ctl.pos).mm, -0.5)
        self.assertGreater(ctl.cfg.muneca, -90)
        self.assertTrue(ctl.aviso.startswith("Detenido"))

    def test_sin_garra_montada_no_se_mueve_la_mano(self):
        ctl = Controlador(Config(garra_montada=False))
        with self.assertRaises(ValueError):
            ctl.mover_auxiliar("garra", 50)

    def test_el_estado_lleva_la_mano(self):
        self.ctl.mover_auxiliar("garra", 40)
        self._pasos(200)
        mano = self.ctl.estado()["mano"]
        self.assertTrue(mano["montada"])
        self.assertEqual(mano["garra"], 40)
        self.assertIn("dedos", self.ctl.estado()["puntos"])


if __name__ == "__main__":
    unittest.main()
