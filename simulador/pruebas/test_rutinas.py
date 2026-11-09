import tempfile
import time
import unittest
from pathlib import Path

from motor.config import Articulacion, Config
from motor.control import Controlador
from motor.rutinas import Rutinas, comprobar, limpiar_pasos

RAPIDA = dict(hombro=Articulacion(0, 135, 200, 800), codo=Articulacion(-180, 0, 200, 800),
              torreta=Articulacion(-54, 54, 200, 800), lim_garra=Articulacion(0, 100, 500, 2000))


class Formato(unittest.TestCase):
    def test_hombro_y_codo_van_juntos(self):
        with self.assertRaises(ValueError):
            limpiar_pasos([{"hombro": 90}])

    def test_un_paso_que_no_hace_nada_es_error(self):
        with self.assertRaises(ValueError):
            limpiar_pasos([{"nombre": "nada"}])

    def test_normaliza_y_pone_nombre(self):
        pasos = limpiar_pasos([{"hombro": "90", "codo": -90}, {"espera": 1}])
        self.assertEqual(pasos[0], {"nombre": "Paso 1", "hombro": 90.0, "codo": -90.0})


class Comprobar(unittest.TestCase):
    def test_la_rutina_de_ejemplo_no_choca(self):
        cfg = Config(reposo_codo=-180, hombro=Articulacion(0, 123, 35, 70), codo=Articulacion(-180, -58.1, 35, 70))
        pasos = limpiar_pasos(__import__("json").load(open(Path(__file__).parent.parent / "datos/rutinas/cajita.json"))["pasos"])
        problemas, segundos = comprobar(cfg, (90, -180), pasos)
        self.assertEqual(problemas, [])
        self.assertGreater(segundos, 10)

    def test_avisa_si_un_paso_es_imposible(self):
        # El planificador flexiona el codo si puede; esto queda fuera de los límites del hombro
        problemas, _ = comprobar(Config(), (90, -91), limpiar_pasos([{"nombre": "Bajar", "hombro": 10, "codo": -60}]))
        self.assertEqual(len(problemas), 1)
        self.assertIn("Bajar", problemas[0])

    def test_avisa_si_mover_la_mano_choca(self):
        cfg = Config(muneca=0)
        problemas, _ = comprobar(cfg, (45, -70), limpiar_pasos([{"nombre": "Apuntar abajo", "muneca": -90}]))
        self.assertIn("al mover muneca", problemas[0])


class Ejecutar(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.ctl = Controlador(Config(**RAPIDA))
        self.ctl.pos = [90, -91]
        self.ctl.iniciar()
        self.rutinas = Rutinas(self.ctl, self.dir.name)

    def tearDown(self):
        self.rutinas.detener()
        self.dir.cleanup()

    def _esperar_fin(self, limite=10):
        fin = time.monotonic() + limite
        while self.rutinas.estado()["activa"] and time.monotonic() < fin:
            time.sleep(0.05)

    def test_ejecuta_los_pasos_en_orden(self):
        pasos = [{"nombre": "Abrir", "garra": 100}, {"nombre": "Ir", "hombro": 80, "codo": -80, "giro": 20},
                 {"nombre": "Cerrar", "garra": 30}]
        self.rutinas.ejecutar("prueba", pasos)
        self._esperar_fin()
        estado = self.rutinas.estado()
        self.assertEqual(estado["aviso"], "Terminada")
        self.assertEqual(estado["paso"], 3)
        self.assertAlmostEqual(self.ctl.pos[0], 80)
        self.assertAlmostEqual(self.ctl.pos[1], -80)
        self.assertEqual((self.ctl.cfg.giro, self.ctl.cfg.garra), (20, 30))

    def test_no_arranca_si_algun_paso_choca(self):
        with self.assertRaises(ValueError):
            Rutinas(Controlador(Config()), self.dir.name).ejecutar("mala", [{"hombro": 10, "codo": -60}])

    def test_detener_la_corta(self):
        self.rutinas.ejecutar("larga", [{"espera": 5}, {"hombro": 60, "codo": -60}])
        time.sleep(0.3)
        self.rutinas.detener()
        estado = self.rutinas.estado()
        self.assertFalse(estado["activa"])
        self.assertEqual(estado["aviso"], "Detenida")
        self.assertEqual(self.ctl.pos, [90, -91])

    def test_guardar_y_leer(self):
        self.rutinas.guardar("ida_y_vuelta", [{"hombro": 80, "codo": -80}])
        self.assertEqual(self.rutinas.lista(), ["ida_y_vuelta"])
        self.assertEqual(self.rutinas.leer("ida_y_vuelta")[0]["hombro"], 80)
        with self.assertRaises(ValueError):
            self.rutinas.guardar("../fuera", [{"hombro": 80, "codo": -80}])


if __name__ == "__main__":
    unittest.main()
