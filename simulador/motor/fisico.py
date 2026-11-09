"""Brazo real, etapa B1: mover los servos para calibrarlos.

Los dos hombros mueven el mismo eje y se mueven SIEMPRE juntos, espejados
alrededor del pulso donde se alinearon. Un hombro solo tendría que arrastrar
la caja de engranajes del otro, que sin señal queda trabada: se oye forzar
(observado por el usuario el 28/10).
"""
import math
import threading
import time

from .calibracion import CENTRO_ESPEJO, us_para
from .nano import NUM_INICIO

US_MIN, US_MAX = 700, 2300  # los mismos límites duros que el firmware
# Rango del hombro izquierdo para que su espejo también quede dentro de los límites
IZQ_MIN = max(US_MIN, 2 * CENTRO_ESPEJO - US_MAX)
IZQ_MAX = min(US_MAX, 2 * CENTRO_ESPEJO - US_MIN)


def _pulso(us, minimo=US_MIN, maximo=US_MAX):
    us = float(us)
    if not math.isfinite(us):
        raise ValueError("pulso inválido")
    return min(max(us, minimo), maximo)


class Fisico:
    def __init__(self, nano, calibracion):
        self.nano = nano
        self.cal = calibracion
        self._parar = threading.Event()
        self._hilo = None

    def estado(self):
        return {**self.nano.estado(), "yendo_a_inicio": self._hilo is not None and self._hilo.is_alive()}

    def guardar_inicio(self, us_izq=None, us_codo=None):
        """Guarda como pose de inicio la actual (o la indicada) para que el Nano vaya ahí al encender."""
        servos = self.nano.estado()["servos"]
        if us_izq is None or us_codo is None:
            if not all(s["activo"] for s in servos[:NUM_INICIO]):
                raise ValueError("Activa los hombros y el codo en la pose que quieres como inicio")
            us_izq, us_codo = servos[0]["us"], servos[2]["us"]
        izq = self.cal.acotar("hombro_izq", _pulso(us_izq, IZQ_MIN, IZQ_MAX))
        codo = self.cal.acotar("codo", _pulso(us_codo))
        self.nano.guardar_inicio([izq, 2 * CENTRO_ESPEJO - izq, codo])

    def ir_a_inicio(self):
        inicio = self.nano.estado()["inicio"]
        if not inicio:
            raise ValueError("No hay pose de inicio guardada en el Nano")
        self._cancelar()
        self._hilo = threading.Thread(target=self._ir_a_inicio, args=(inicio,), daemon=True)
        self._hilo.start()

    def _ir_a_inicio(self, inicio):
        # La pose de inicio tiene los hombros arriba: primero suben ellos y
        # recién entonces se pliega el codo, para que el antebrazo no baje
        # hacia la mesa con el brazo todavía inclinado.
        try:
            self._hombros(inicio[0])
            if self._esperar_llegada(0, inicio[0]):
                self._codo(inicio[2])
        except ConnectionError:
            pass

    def _esperar_llegada(self, i, us, limite=15.0):
        fin = time.monotonic() + limite
        while time.monotonic() < fin:
            s = self.nano.estado()["servos"][i]
            if s["activo"] and s["us"] is not None and abs(s["us"] - us) <= 3:
                return True
            if self._parar.wait(0.05):
                return False
        return False

    def _cancelar(self):
        if self._hilo is not None and self._hilo.is_alive():
            self._parar.set()
            self._hilo.join(timeout=2)
        self._parar.clear()
        self._hilo = None

    def mover_hombros(self, us_izq):
        self._cancelar()  # una orden del usuario corta «ir a inicio»
        self._hombros(us_izq)

    def mover_codo(self, us):
        self._cancelar()
        self._codo(us)

    def _hombros(self, us_izq):
        izq = self.cal.acotar("hombro_izq", _pulso(us_izq, IZQ_MIN, IZQ_MAX))
        # Si estaban sueltos, el firmware los activa en estos pulsos a la vez
        self.nano.objetivo(0, izq)
        self.nano.objetivo(1, 2 * CENTRO_ESPEJO - izq)

    def _codo(self, us):
        self.nano.objetivo(2, self.cal.acotar("codo", _pulso(us)))

    def soltar(self):
        self._cancelar()
        self.nano.soltar_todos()

    def sostener_hombros(self, angulo):
        self._cancelar()
        izq, der = self.cal.ajuste("hombro_izq"), self.cal.ajuste("hombro_der")
        if not izq or not der:
            raise ValueError("Primero calibra los hombros (al menos 2 puntos)")
        us_izq = self.cal.acotar("hombro_izq", _pulso(us_para(izq, angulo), IZQ_MIN, IZQ_MAX))
        if der.get("espejo"):
            us_der = 2 * CENTRO_ESPEJO - us_izq
        else:
            us_der = _pulso(us_para(der, angulo))
        self.nano.objetivo(0, us_izq)
        self.nano.objetivo(1, us_der)
