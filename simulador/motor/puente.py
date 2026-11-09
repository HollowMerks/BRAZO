"""Brazo real siguiendo al simulador (etapa B2).

Con el puente habilitado, cada pose del bucle de control (que ya respeta los
límites y protege la mesa) se convierte a pulsos con la calibración y se envía
al Nano. Habilitar no mueve nada: primero el simulador se coloca en la pose
donde está el brazo real, deducida de los pulsos que informa el Nano.

Los hombros van siempre espejados alrededor de CENTRO_ESPEJO, como en fisico.py.
"""
import math

from .calibracion import CENTRO_ESPEJO, us_para
from .config import Articulacion, Config
from .fisico import IZQ_MAX, IZQ_MIN, US_MAX, US_MIN, _pulso
from .nano import NUM_INICIO

# El firmware limita cada servo a 420 µs/s y 840 µs/s²; el simulador debe ir
# algo por debajo para que el brazo real no se quede atrás del dibujo
VMAX_US = 400
AMAX_US = 800
# Sin topes marcados, el dibujo llega hasta donde llegan los pulsos del firmware, dentro de
# lo mecánicamente posible. Si pudiera pasarse, el brazo real se quedaría atrás sin avisar
RANGO_LIBRE = {"hombro": ((IZQ_MIN, IZQ_MAX), (0, 180)), "codo": ((US_MIN, US_MAX), (-180, 0))}


class Puente:
    def __init__(self, fisico, control):
        self.fisico = fisico
        self.control = control
        self.habilitado = False
        self._ultimo = None
        self._reinicios = None
        self._informar("")

    # --- conversión ---

    def _ajustes(self):
        cal = self.fisico.cal
        hombro, codo = cal.ajuste("hombro_izq"), cal.ajuste("codo")
        if not hombro:
            raise ValueError("Falta calibrar los hombros")
        if not codo:
            raise ValueError("Falta calibrar el codo (2 puntos)")
        return hombro, codo

    def pulsos(self, hombro, codo):
        aj_h, aj_c = self._ajustes()
        cal = self.fisico.cal
        izq = cal.acotar("hombro_izq", _pulso(us_para(aj_h, hombro), IZQ_MIN, IZQ_MAX))
        c = cal.acotar("codo", _pulso(us_para(aj_c, codo)))
        return izq, 2 * CENTRO_ESPEJO - izq, c

    def angulos(self, us_izq, us_codo):
        aj_h, aj_c = self._ajustes()
        return (aj_h["pendiente"] * us_izq + aj_h["corte"],
                aj_c["pendiente"] * us_codo + aj_c["corte"])

    # --- habilitar / deshabilitar ---

    def config_ajustada(self, cfg):
        """La config del simulador recortada a lo que el brazo real puede hacer, y la lista de cambios."""
        aj_h, aj_c = self._ajustes()
        cal = self.fisico.cal
        datos = cfg.a_dict()
        cambios = []
        for nombre, servo, aj in (("hombro", "hombro_izq", aj_h), ("codo", "codo", aj_c)):
            art = datos[nombre]
            # Los límites marcados en el brazo real mandan; se redondea hacia adentro
            pulsos, mecanica = RANGO_LIBRE[nombre]
            minimo, maximo = (a if a is not None else b for a, b in zip(cal.limites[servo], pulsos))
            extremos = sorted(aj["pendiente"] * us + aj["corte"] for us in (minimo, maximo))
            nuevo = [max(math.ceil(extremos[0] * 10) / 10, mecanica[0]),
                     min(math.floor(extremos[1] * 10) / 10, mecanica[1])]
            if [art["minimo"], art["maximo"]] != nuevo:
                art["minimo"], art["maximo"] = nuevo
                cambios.append(f"{nombre}: límites {nuevo[0]:g}° a {nuevo[1]:g}°")
            vmax = round(VMAX_US * abs(aj["pendiente"]), 1)
            amax = round(AMAX_US * abs(aj["pendiente"]), 1)
            if art["vmax"] > vmax or art["amax"] > amax:
                art["vmax"], art["amax"] = min(art["vmax"], vmax), min(art["amax"], amax)
                cambios.append(f"{nombre}: velocidad {art['vmax']:g}°/s")
        inicio = self.fisico.nano.estado().get("inicio")
        if inicio:
            h, c = (round(a, 1) for a in self.angulos(inicio[0], inicio[2]))
            if (h, c) != (datos["reposo_hombro"], datos["reposo_codo"]):
                datos["reposo_hombro"], datos["reposo_codo"] = h, c
                cambios.append(f"reposo = pose de inicio del Nano ({h:g}°, {c:g}°)")
        nuevo = Config.desde_dict(datos)
        errores = nuevo.errores()
        if errores:
            raise ValueError("La calibración no encaja con el simulador: " + "; ".join(errores))
        return nuevo, cambios

    def habilitar(self):
        """Coloca el simulador donde está el brazo real y empieza a seguirlo. Devuelve los cambios de config."""
        estado = self.fisico.nano.estado()
        if not estado.get("responde", True):
            raise ConnectionError("el Nano no responde")
        servos = estado["servos"]
        if servos[0]["us"] is None or servos[2]["us"] is None:
            raise ValueError("Todavía no se sabe dónde está el brazo real")
        # Sin señal, el pulso informado es el último que tuvo, no dónde está el brazo:
        # pudo moverse a mano, y al seguir al dibujo el servo saltaría a ese pulso
        if not all(s["activo"] for s in servos[:NUM_INICIO]):
            raise ValueError("Hombros o codo sin señal: actívalos en la pose real antes de habilitar")
        cfg, cambios = self.config_ajustada(self.control.cfg)
        hombro, codo = self.angulos(servos[0]["us"], servos[2]["us"])
        tol = 1.0
        if not (cfg.hombro.minimo - tol <= hombro <= cfg.hombro.maximo + tol
                and cfg.codo.minimo - tol <= codo <= cfg.codo.maximo + tol):
            raise ValueError(f"El brazo real está fuera de los límites (hombro {hombro:.0f}°, codo {codo:.0f}°)")
        if cambios:
            self.control.actualizar_config(cfg)
        hombro = min(max(hombro, cfg.hombro.minimo), cfg.hombro.maximo)
        codo = min(max(codo, cfg.codo.minimo), cfg.codo.maximo)
        self.control.sincronizar(hombro, codo)
        self._ultimo = None
        self._reinicios = estado.get("reinicios")
        self.habilitado = True
        self.control.salida = self._enviar
        self._informar("")
        return cfg, cambios

    def pose_real(self):
        """Dónde está el brazo real según sus pulsos y la calibración (None si no se puede saber)."""
        try:
            estado = self.fisico.nano.estado()
            servos = estado["servos"]
            if not estado.get("responde", True) or servos[0]["us"] is None or servos[2]["us"] is None:
                return None
            return self.angulos(servos[0]["us"], servos[2]["us"])
        except (ValueError, KeyError):
            return None

    def deshabilitar(self, aviso=""):
        self.habilitado = False
        self.control.salida = None
        self._informar(aviso)

    def _informar(self, aviso):
        self.control.real = {"disponible": True, "habilitado": self.habilitado, "aviso": aviso}
        self.control.pose_real = self.pose_real

    # --- envío (desde el bucle de control) ---

    def _enviar(self, hombro, codo):
        nano = self.fisico.nano
        try:
            if nano.estado().get("reinicios") != self._reinicios:
                # Tras reiniciarse fue a su pose de inicio: el dibujo ya no coincide
                self.deshabilitar("El Nano se reinició: brazo real deshabilitado")
                return
            pulsos = self.pulsos(hombro, codo)
            if self._ultimo and all(abs(p - u) < 1 for p, u in zip(pulsos, self._ultimo)):
                return
            for i, us in enumerate(pulsos):
                nano.objetivo(i, us)
            self._ultimo = pulsos
        except ConnectionError:
            self.deshabilitar("Se perdió la conexión con el Nano: brazo real deshabilitado")
