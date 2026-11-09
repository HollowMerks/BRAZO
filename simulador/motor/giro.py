"""Giro de la torreta en el brazo real: el 4.º servo, en el mismo Nano que los demás.

Igual que con el brazo, conectar no mueve nada: el servo sigue al simulador solo
después de habilitarlo, y si estaba sostenido en una posición, el simulador se
coloca ahí en vez de moverlo.
"""
import time

from .nano import GIRO

ARRANQUE = 3.2  # s: el firmware tarda 3 s en activar el giro y mientras tanto no atiende órdenes


class PuenteGiro:
    def __init__(self, nano, control):
        self.nano = nano
        self.control = control
        self.habilitado = False
        self.aviso = ""
        self._ultimo = None
        self._reinicios = None
        self._arranca_hasta = 0.0
        control.giro_real = self.informe

    def pulso(self, giro):
        cfg = self.control.cfg
        return cfg.giro_centro_us + giro * cfg.giro_us_por_grado

    def angulo(self, us):
        cfg = self.control.cfg
        return (us - cfg.giro_centro_us) / cfg.giro_us_por_grado

    def informe(self):
        """Lo que la página muestra del servo."""
        estado = self.nano.estado()
        s = estado["servos"][GIRO]
        return {"habilitado": self.habilitado, "responde": estado["responde"], "activo": s["activo"],
                "us": s["us"], "aviso": self.aviso, "arrancando": time.monotonic() < self._arranca_hasta}

    def habilitar(self):
        """Empieza a seguir al simulador. Devuelve True si hubo que activar el servo (eso sí lo mueve)."""
        estado = self.nano.estado()
        if not estado["responde"]:
            raise ConnectionError("no responde; ¿tiene grabado BrazoNano 6?")
        s = estado["servos"][GIRO]
        art = self.control.cfg.torreta
        activar = not s["activo"]
        if activar:
            self.nano.activar(GIRO, self.pulso(self.control.cfg.giro))
            self._arranca_hasta = time.monotonic() + ARRANQUE
        else:
            giro = self.angulo(s["us"])
            if not art.minimo - 1 <= giro <= art.maximo + 1:
                raise ValueError(f"El servo está fuera de los límites del giro ({giro:.0f}°)")
            self.control.sincronizar_giro(min(max(giro, art.minimo), art.maximo))
        self._ultimo = None
        self._reinicios = estado["reinicios"]
        self.aviso = ""
        self.habilitado = True
        self.control.salida_giro = self._enviar
        return activar

    def deshabilitar(self, aviso=""):
        self.habilitado = False
        self.control.salida_giro = None
        self.aviso = aviso

    def soltar(self):
        self.deshabilitar()
        self.nano.soltar(GIRO)

    def _enviar(self, giro):
        if time.monotonic() < self._arranca_hasta:
            return
        try:
            if self.nano.estado()["reinicios"] != self._reinicios:
                self.deshabilitar("El Nano se reinició: servo de giro deshabilitado")
                return
            us = self.pulso(giro)
            if self._ultimo is not None and abs(us - self._ultimo) < 1:
                return
            self.nano.objetivo(GIRO, us)
            self._ultimo = us
        except ConnectionError:
            self.deshabilitar("Se perdió la conexión con el Nano: servo de giro deshabilitado")
