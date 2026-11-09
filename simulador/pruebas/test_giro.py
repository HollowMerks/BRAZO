import unittest

from motor.cinematica import holgura
from motor.config import Articulacion, Config
from motor.control import TOLERANCIA_GIRO, Controlador
from motor.giro import PuenteGiro
from motor.nano import GIRO, leer_informe
from motor.trayectoria import PASO


class NanoFalso:
    def __init__(self, activo=True, us=1500):
        self.servos = [{"activo": True, "us": 1472} for _ in range(3)] + [{"activo": activo, "us": us}]
        self.responde = True
        self.reinicios = 1
        self.ordenes = []

    def activar(self, servo, us):
        self.ordenes.append(("A", servo, round(us)))

    def objetivo(self, servo, us):
        self.ordenes.append(("S", servo, round(us)))

    def soltar(self, servo):
        self.ordenes.append(("D", servo, None))

    def estado(self):
        return {"responde": self.responde, "reinicios": self.reinicios, "servos": [dict(s) for s in self.servos]}


class Informe(unittest.TestCase):
    def test_el_giro_es_el_cuarto_servo(self):
        servos = leer_informe("E 1 2070 1 874 1 2000 0 1500")
        self.assertEqual(servos[GIRO], {"activo": False, "us": 1500})

    def test_un_firmware_anterior_no_se_acepta(self):
        self.assertIsNone(leer_informe("E 1 2070 1 874 1 2000"))
        self.assertIsNone(leer_informe("E 1 1500"))


class Torreta(unittest.TestCase):
    def setUp(self):
        self.ctl = Controlador(Config())

    def _pasos(self, n):
        for _ in range(n):
            self.ctl._paso(PASO)

    def test_llega_al_objetivo_sin_pasarse_de_velocidad(self):
        self.ctl.girar(30)
        antes = 0.0
        for _ in range(600):
            self.ctl._paso(PASO)
            giro = self.ctl.cfg.giro
            self.assertLessEqual((giro - antes) / PASO, self.ctl.cfg.torreta.vmax + 1e-6)
            self.assertLessEqual(giro, 30 + 0.05)
            antes = giro
        self.assertEqual(self.ctl.cfg.giro, 30)
        self.assertEqual(self.ctl.vel_giro, 0)

    def test_no_sale_de_los_limites(self):
        self.assertEqual(self.ctl.girar(500), 54)
        self.assertEqual(self.ctl.girar(-500), -54)

    def test_detener_frena_sin_volver_atras(self):
        self.ctl.girar(50)
        self._pasos(100)
        self.ctl.detener()
        antes = self.ctl.cfg.giro
        for _ in range(100):
            self.ctl._paso(PASO)
            self.assertGreaterEqual(self.ctl.cfg.giro, antes - 1e-9)
            antes = self.ctl.cfg.giro
        self.assertEqual(self.ctl.vel_giro, 0)
        self.assertLess(self.ctl.cfg.giro, 50)

    def test_no_gira_durante_un_plan(self):
        self.assertTrue(self.ctl.mover((60, -60))["valido"])
        with self.assertRaises(ValueError):
            self.ctl.girar(30)

    def test_se_detiene_si_el_giro_mete_la_caja_bajo_el_brazo(self):
        # Antebrazo bajo y torreta girando hasta que lo largo de la caja queda debajo
        ctl = Controlador(Config(giro=90, torreta=Articulacion(-180, 180, 10, 20)))
        ctl.pos = [50, -130]
        self.assertGreater(holgura(ctl.cfg, *ctl.pos).mm, 0)
        ctl.girar(180)
        for _ in range(1000):
            ctl._paso(PASO)
            self.assertGreaterEqual(holgura(ctl.cfg, *ctl.pos).mm, -TOLERANCIA_GIRO)
        self.assertLess(ctl.cfg.giro, 180)
        self.assertTrue(ctl.aviso.startswith("Detenido"))
        self.assertIn("base", ctl.aviso)


    def _girando_con_el_brazo_real_en(self, dibujo, real):
        ctl = Controlador(Config(giro=90, torreta=Articulacion(-180, 180, 10, 20)))
        ctl.pos = list(dibujo)
        ctl.salida_giro = lambda giro: None
        ctl.real = {"habilitado": False}
        ctl.pose_real = lambda: real
        ctl.girar(180)
        for _ in range(1000):
            ctl._paso(PASO)
        return ctl

    def test_con_el_brazo_sin_seguir_al_dibujo_protege_la_pose_real(self):
        # El dibujo quedó abajo, sobre la caja, pero el brazo real está parado y libre
        ctl = self._girando_con_el_brazo_real_en((50, -130), (90, -91))
        self.assertEqual(ctl.cfg.giro, 180)
        self.assertNotIn("Detenido", ctl.aviso)

    def test_el_brazo_real_abajo_detiene_el_giro_aunque_el_dibujo_este_libre(self):
        ctl = self._girando_con_el_brazo_real_en((90, -91), (50, -130))
        self.assertLess(ctl.cfg.giro, 180)
        self.assertTrue(ctl.aviso.startswith("Detenido"))

    def test_justo_en_el_margen_unas_decimas_no_lo_detienen(self):
        ctl = Controlador(Config())
        ctl.pos = [75.56, -162.09]  # holgura -0,08 mm, como el 31/10
        ctl.girar(10)
        self._avanzar(ctl, 400)
        self.assertEqual(ctl.cfg.giro, 10)

    def _avanzar(self, ctl, n):
        for _ in range(n):
            ctl._paso(PASO)


class Puente(unittest.TestCase):
    def setUp(self):
        self.ctl = Controlador(Config())
        self.nano = NanoFalso()
        self.puente = PuenteGiro(self.nano, self.ctl)

    def test_habilitar_con_el_servo_sostenido_no_lo_mueve(self):
        self.nano.servos[GIRO]["us"] = 1611  # ya está ~10° girado
        self.assertFalse(self.puente.habilitar())
        self.assertEqual(self.nano.ordenes, [])
        self.assertAlmostEqual(self.ctl.cfg.giro, 10, places=1)
        self.assertEqual(self.ctl.giro_objetivo, self.ctl.cfg.giro)
        # El primer envío repite el pulso donde ya está
        self.ctl.salida_giro(self.ctl.cfg.giro)
        self.assertEqual(self.nano.ordenes, [("S", GIRO, 1611)])

    def test_habilitar_con_el_servo_suelto_lo_activa_en_el_giro_del_dibujo(self):
        self.nano.servos[GIRO]["activo"] = False
        self.ctl.sincronizar_giro(20)
        self.assertTrue(self.puente.habilitar())
        self.assertEqual(self.nano.ordenes, [("A", GIRO, 1722)])
        # Mientras se activa, el sketch no atiende órdenes
        self.ctl.salida_giro(25)
        self.assertEqual(len(self.nano.ordenes), 1)

    def test_el_servo_sigue_a_la_torreta(self):
        self.puente.habilitar()
        self.ctl.girar(20)
        for _ in range(300):
            self.ctl._paso(PASO)
            self.ctl.salida_giro(self.ctl.cfg.giro)
        pulsos = [us for tipo, _, us in self.nano.ordenes if tipo == "S"]
        self.assertEqual(pulsos[-1], 1722)
        self.assertEqual(pulsos, sorted(pulsos))

    def test_sin_cambios_no_escribe_al_puerto(self):
        self.puente.habilitar()
        for _ in range(10):
            self.ctl.salida_giro(0)
        self.assertEqual(len(self.nano.ordenes), 1)

    def test_el_signo_invierte_el_sentido(self):
        self.ctl.cfg.giro_us_por_grado = -11.11
        self.assertAlmostEqual(self.puente.pulso(10), 1388.9)
        self.assertAlmostEqual(self.puente.angulo(1388.9), 10)

    def test_un_nano_que_no_responde_no_se_habilita(self):
        self.nano.responde = False
        with self.assertRaises(ConnectionError):
            self.puente.habilitar()
        self.assertIsNone(self.ctl.salida_giro)

    def test_servo_fuera_de_limites_no_se_habilita(self):
        self.nano.servos[GIRO]["us"] = 2400
        with self.assertRaises(ValueError):
            self.puente.habilitar()
        self.assertFalse(self.puente.habilitado)

    def test_reinicio_del_nano_deshabilita(self):
        self.puente.habilitar()
        self.nano.reinicios += 1
        self.ctl.salida_giro(5)
        self.assertFalse(self.puente.habilitado)
        self.assertIn("reinició", self.puente.informe()["aviso"])
        self.assertEqual(self.nano.ordenes, [])

    def test_perder_el_puerto_deshabilita(self):
        self.puente.habilitar()

        def sin_puerto(servo, us):
            raise ConnectionError("desenchufado")

        self.nano.objetivo = sin_puerto
        self.ctl.salida_giro(5)
        self.assertFalse(self.puente.habilitado)
        self.assertIn("conexión", self.puente.aviso)

    def test_soltar_deshabilita_y_corta_la_senal(self):
        self.puente.habilitar()
        self.puente.soltar()
        self.assertFalse(self.puente.habilitado)
        self.assertEqual(self.nano.ordenes, [("D", GIRO, None)])


if __name__ == "__main__":
    unittest.main()
