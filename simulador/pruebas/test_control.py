import time
import unittest

from motor.cinematica import holgura, puntos
from motor.config import Config
from motor.control import Controlador
from motor.trayectoria import PASO


class Control(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()
        self.ctl = Controlador(self.cfg)

    def _pasos(self, n):
        for _ in range(n):
            self.ctl._paso(PASO)

    def test_bajar_el_hombro_con_joystick_nunca_toca_la_mesa(self):
        # Antebrazo bastante caído y hombro bajando a fondo durante 6 s
        self.ctl.pos = [90, -120]
        for _ in range(300):
            self.ctl.joystick({"modo": "articulaciones", "hombro": -1, "codo": 0})
            self.ctl._paso(PASO)
            self.assertGreaterEqual(holgura(self.cfg, *self.ctl.pos).mm, -1e-6)
        self.assertLess(self.ctl.pos[0], 40)          # el hombro sí bajó
        self.assertGreater(self.ctl.pos[1], -120)     # porque el codo se fue flexionando

    def test_codo_hacia_la_mesa_se_detiene_sin_llevar_la_contraria(self):
        self.ctl.pos = [30, -60]
        for _ in range(400):
            antes = self.ctl.pos[1]
            self.ctl.joystick({"modo": "articulaciones", "hombro": 0, "codo": -1})
            self.ctl._paso(PASO)
            self.assertLessEqual(self.ctl.pos[1], antes + 1e-9)
            self.assertGreaterEqual(holgura(self.cfg, *self.ctl.pos).mm, -1e-6)
        self.assertTrue(self.ctl.aviso.startswith("Detenido"))

    def test_detenido_contra_la_caja_no_avanza_a_tirones(self):
        # Torreta girada hacia la caja y el antebrazo plegándose sobre ella
        ctl = Controlador(Config(giro=180))
        ctl.pos = [40, -90]
        avisos = []
        for _ in range(300):
            ctl.joystick({"modo": "articulaciones", "hombro": 0, "codo": -1})
            ctl._paso(PASO)
            avisos.append(ctl.aviso)
        primero = next(i for i, a in enumerate(avisos) if a.startswith("Detenido"))
        self.assertIn("base", avisos[primero])
        # Una vez detenido sigue detenido: ni el aviso ni el brazo van y vienen
        self.assertTrue(all(a.startswith("Detenido") for a in avisos[primero:]))
        # Y quedó justo en el límite, no un paso antes
        self.assertAlmostEqual(holgura(ctl.cfg, *ctl.pos).mm, 0, delta=0.05)

    def test_sin_noticias_del_joystick_frena(self):
        self.ctl.joy = ({"modo": "articulaciones", "hombro": 1, "codo": 0}, time.monotonic() - 1)
        self.ctl.vel = [20.0, 0.0]
        self._pasos(50)
        self.assertEqual(self.ctl.vel, [0.0, 0.0])

    def test_modo_punta_baja_en_vertical(self):
        x0, y0 = puntos(self.cfg, *self.ctl.pos)["punta"]
        for _ in range(60):
            self.ctl.joystick({"modo": "punta", "x": 0, "y": -1})
            self.ctl._paso(PASO)
        x1, y1 = puntos(self.cfg, *self.ctl.pos)["punta"]
        self.assertLess(y1, y0 - 20)
        self.assertLess(abs(x1 - x0), 5)

    def test_plan_ejecutado_llega_al_destino(self):
        r = self.ctl.mover((60, -60))
        self.assertTrue(r["valido"], r["motivo"])
        self._pasos(1000)
        self.assertIsNone(self.ctl.plan)
        self.assertAlmostEqual(self.ctl.pos[0], 60)
        self.assertAlmostEqual(self.ctl.pos[1], -60)


if __name__ == "__main__":
    unittest.main()
