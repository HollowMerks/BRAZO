import tempfile
import unittest
from pathlib import Path

from motor.calibracion import Calibracion
from motor.config import Config
from motor.control import Controlador
from motor.fisico import Fisico
from motor.puente import VMAX_US, Puente
from motor.trayectoria import PASO


class NanoFalso:
    def __init__(self, pulsos=(2070, 874, 2000)):
        self.servos = [{"activo": True, "us": us} for us in pulsos]
        self.inicio = list(pulsos)
        self.reinicios = 1
        self.ordenes = []

    def objetivo(self, servo, us):
        self.ordenes.append((servo, round(us)))
        self.servos[servo] = {"activo": True, "us": round(us)}

    def estado(self):
        return {"responde": True, "servos": [dict(s) for s in self.servos],
                "inicio": self.inicio, "reinicios": self.reinicios}


class PuenteReal(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        cal = Calibracion(Path(self.dir.name) / "c.json")
        # Hombros: los puntos reales del 28/10. Codo: inventado solo para la prueba
        cal.agregar("hombro_izq", 1270, 15)
        cal.agregar("hombro_izq", 2070, 90)
        cal.fijar_limite("hombro_izq", 0, 1270)
        cal.fijar_limite("hombro_izq", 1, 2070)
        cal.agregar("codo", 700, -30)
        cal.agregar("codo", 2000, -150)
        cal.fijar_limite("codo", 0, 700)
        cal.fijar_limite("codo", 1, 2000)
        self.nano = NanoFalso()
        self.control = Controlador(Config(hombro=Config().hombro, reposo_hombro=90))
        self.puente = Puente(Fisico(self.nano, cal), self.control)

    def tearDown(self):
        self.dir.cleanup()

    def test_pulsos_y_angulos_son_inversos(self):
        izq, der, codo = self.puente.pulsos(60, -100)
        self.assertEqual(round(izq + der), 2944)
        h, c = self.puente.angulos(izq, codo)
        self.assertAlmostEqual(h, 60, places=6)
        self.assertAlmostEqual(c, -100, places=6)

    def test_habilitar_no_mueve_el_brazo(self):
        self.puente.habilitar()
        self.assertEqual(self.nano.ordenes, [])
        h, c = self.puente.angulos(2070, 2000)
        self.assertAlmostEqual(self.control.pos[0], h)
        self.assertAlmostEqual(self.control.pos[1], c)
        # El primer envío repite los pulsos donde ya está: tampoco hay salto
        self.control.salida(*self.control.pos)
        self.assertEqual(self.nano.ordenes, [(0, 2070), (1, 874), (2, 2000)])

    def test_con_un_servo_sin_senal_no_se_habilita(self):
        # Su pulso es el último que tuvo: el brazo pudo moverse a mano y saltaría ahí
        self.nano.servos[2]["activo"] = False
        with self.assertRaises(ValueError):
            self.puente.habilitar()
        self.assertFalse(self.puente.habilitado)
        self.assertEqual(self.nano.ordenes, [])

    def test_config_se_recorta_a_lo_calibrado(self):
        cfg, cambios = self.puente.habilitar()
        self.assertEqual((cfg.codo.minimo, cfg.codo.maximo), (-150, -30))
        self.assertLessEqual(cfg.codo.vmax, VMAX_US * 120 / 1300 + 0.1)
        self.assertAlmostEqual(cfg.reposo_hombro, 90)
        self.assertTrue(cambios)

    def test_sin_topes_marcados_el_dibujo_no_se_pasa_de_los_pulsos(self):
        for extremo in (0, 1):
            self.puente.fisico.cal.fijar_limite("codo", extremo, None)
        cfg, _ = self.puente.config_ajustada(self.control.cfg)
        self.assertEqual(cfg.codo.maximo, -30)  # 700 µs, el tope del firmware
        self.assertAlmostEqual(cfg.codo.minimo, -150 - 300 * 120 / 1300, delta=0.2)  # 2300 µs

    def test_el_brazo_real_sigue_al_simulador(self):
        self.puente.habilitar()
        self.control.mover((70, -60))
        for _ in range(600):
            self.control._paso(PASO)
            self.control.salida(*self.control.pos)
        izq, der, codo = self.nano.ordenes[-3][1], self.nano.ordenes[-2][1], self.nano.ordenes[-1][1]
        self.assertEqual((izq, der, codo), tuple(round(p) for p in self.puente.pulsos(70, -60)))

    def test_reinicio_del_nano_deshabilita(self):
        self.puente.habilitar()
        self.nano.reinicios += 1
        self.control.salida(*self.control.pos)
        self.assertFalse(self.puente.habilitado)
        self.assertIn("reinició", self.control.real["aviso"])

    def test_sin_calibrar_el_codo_no_habilita(self):
        self.puente.fisico.cal.puntos["codo"] = []
        with self.assertRaises(ValueError):
            self.puente.habilitar()


if __name__ == "__main__":
    unittest.main()


class CalibrarConElPuenteHabilitado(unittest.TestCase):
    """Lo que hace servidor._cambiar_calibracion: deshabilitar, cambiar y volver a habilitar."""

    def test_cambiar_la_calibracion_no_hace_saltar_el_brazo(self):
        with tempfile.TemporaryDirectory() as d:
            cal = Calibracion(Path(d) / "c.json")
            cal.agregar("hombro_izq", 1270, 15)
            cal.agregar("hombro_izq", 2070, 90)
            cal.agregar("codo", 700, -30)
            cal.agregar("codo", 2000, -150)
            nano = NanoFalso()
            control = Controlador(Config(hombro=Config().hombro, reposo_hombro=90))
            puente = Puente(Fisico(nano, cal), control)
            puente.habilitar()
            puente.deshabilitar()
            cal.agregar("hombro_izq", 1891, 90)  # el vertical resultó estar en otro pulso
            cal.puntos["hombro_izq"] = [p for p in cal.puntos["hombro_izq"] if p[0] != 2070]
            puente.habilitar()
            control.salida(*control.pos)
            # El brazo sigue en 2070: el dibujo se movió, el servo no
            self.assertEqual(nano.ordenes[-3:], [(0, 2070), (1, 874), (2, 2000)])
