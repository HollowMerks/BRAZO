import tempfile
import unittest
from pathlib import Path

from motor.calibracion import Calibracion
from motor.fisico import Fisico


class NanoFalso:
    """Simula el Nano: los servos llegan al instante al pulso pedido."""

    def __init__(self):
        self.ordenes = []
        self.servos = [{"activo": False, "us": 1472} for _ in range(3)]
        self.inicio = None

    def objetivo(self, servo, us):
        self.ordenes.append((servo, round(us)))
        self.servos[servo] = {"activo": True, "us": round(us)}

    def soltar_todos(self):
        self.ordenes.append("X")

    def guardar_inicio(self, pulsos):
        self.inicio = [round(us) for us in pulsos]

    def estado(self):
        return {"servos": [dict(s) for s in self.servos], "inicio": self.inicio}


class Hombros(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.nano = NanoFalso()
        self.cal = Calibracion(Path(self.dir.name) / "c.json")
        self.fisico = Fisico(self.nano, self.cal)

    def tearDown(self):
        self.dir.cleanup()

    def test_se_mueven_juntos_y_espejados(self):
        self.fisico.mover_hombros(1572)
        self.assertEqual(self.nano.ordenes, [(0, 1572), (1, 1372)])

    def test_el_espejo_tambien_respeta_los_limites(self):
        self.fisico.mover_hombros(2290)  # su espejo (654) quedaría bajo 700
        izq, der = self.nano.ordenes[0][1], self.nano.ordenes[1][1]
        self.assertEqual(izq + der, 2944)
        self.assertGreaterEqual(der, 700)

    def test_sostener_usa_la_calibracion(self):
        self.cal.agregar("hombro_izq", 1372, 80)
        self.cal.agregar("hombro_izq", 1572, 100)
        self.fisico.sostener_hombros(90)
        self.assertEqual(self.nano.ordenes, [(0, 1472), (1, 1472)])

    def test_limite_marcado_frena_a_los_dos_hombros(self):
        self.cal.fijar_limite("hombro_izq", 1, 2070)
        self.fisico.mover_hombros(2200)
        self.assertEqual(self.nano.ordenes, [(0, 2070), (1, 874)])

    def test_limite_del_codo(self):
        self.cal.fijar_limite("codo", 0, 1100)
        self.fisico.mover_codo(900)
        self.assertEqual(self.nano.ordenes, [(2, 1100)])

    def test_limites_al_reves_se_rechazan(self):
        self.cal.fijar_limite("codo", 1, 1500)
        with self.assertRaises(ValueError):
            self.cal.fijar_limite("codo", 0, 1600)

    def test_limites_se_guardan(self):
        self.cal.fijar_limite("hombro_izq", 1, 2070)
        self.assertEqual(Calibracion(self.cal.ruta).limites["hombro_izq"], [None, 2070])

    def test_guardar_inicio_espeja_los_hombros(self):
        self.fisico.guardar_inicio(2070, 2000)
        self.assertEqual(self.nano.inicio, [2070, 874, 2000])

    def test_guardar_inicio_con_la_pose_actual(self):
        self.fisico.mover_hombros(2000)
        self.fisico.mover_codo(1800)
        self.fisico.guardar_inicio()
        self.assertEqual(self.nano.inicio, [2000, 944, 1800])

    def test_guardar_inicio_sin_activar_falla(self):
        with self.assertRaises(ValueError):
            self.fisico.guardar_inicio()

    def test_ir_a_inicio_sube_hombros_antes_de_plegar_el_codo(self):
        self.nano.inicio = [2070, 874, 2000]
        self.fisico.ir_a_inicio()
        self.fisico._hilo.join(timeout=2)
        self.assertEqual(self.nano.ordenes, [(0, 2070), (1, 874), (2, 2000)])

    def test_sostener_sin_calibrar_falla(self):
        with self.assertRaises(ValueError):
            self.fisico.sostener_hombros(90)


if __name__ == "__main__":
    unittest.main()
