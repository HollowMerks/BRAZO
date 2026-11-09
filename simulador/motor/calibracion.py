"""Calibración de cada servo: pares (pulso en µs, ángulo mecánico medido).

Una recta por servo: incluye el sentido de giro (pendiente negativa en el
hombro espejado), el desfase y la escala, que difiere entre servos y es lo
que hace que dos hombros alineados en el centro se separen en los extremos.

Ángulos mecánicos como en config.py: hombro = tramo recto de la pieza gris
respecto a la mesa (90 = vertical); codo = antebrazo respecto a ese tramo.
"""
import json
import os
from pathlib import Path

from .nano import SERVOS

# Los hombros mueven el mismo eje montados uno frente al otro. El 28/10 se
# alinearon mecánicamente en 1472 µs (Servo.write(90)) y con pulsos espejados
# alrededor de ese valor subieron parejos hasta ±45°: el derecho se deduce del
# izquierdo salvo que se le registren puntos propios.
CENTRO_ESPEJO = 1472


def ajustar(puntos):
    """Recta de mínimos cuadrados ángulo = pendiente·us + corte; None con menos de 2 pulsos distintos."""
    if len({us for us, _ in puntos}) < 2:
        return None
    n = len(puntos)
    mx = sum(us for us, _ in puntos) / n
    my = sum(a for _, a in puntos) / n
    sxx = sum((us - mx) ** 2 for us, _ in puntos)
    pendiente = sum((us - mx) * (a - my) for us, a in puntos) / sxx
    corte = my - pendiente * mx
    error = max(abs(a - (pendiente * us + corte)) for us, a in puntos)
    return {"pendiente": pendiente, "corte": corte, "error_max": error}


def us_para(ajuste, angulo):
    return (angulo - ajuste["corte"]) / ajuste["pendiente"]


class Calibracion:
    """Puntos medidos y límites de pulso marcados a mano para cada servo.

    Los límites de los hombros se guardan sobre el izquierdo; el derecho es su espejo.
    """

    def __init__(self, ruta):
        self.ruta = Path(ruta)
        self.puntos = {s: [] for s in SERVOS}
        self.limites = {s: [None, None] for s in SERVOS}  # [mínimo, máximo] en µs
        self.notas = {}
        if self.ruta.exists():
            datos = json.loads(self.ruta.read_text(encoding="utf-8"))
            self.notas = dict(datos.get("notas", {}))
            for s in SERVOS:
                self.puntos[s] = [[float(us), float(a)] for us, a in datos.get("puntos", {}).get(s, [])]
                lim = datos.get("limites", {}).get(s, [None, None])
                self.limites[s] = [None if v is None else float(v) for v in lim]

    def agregar(self, servo, us, angulo):
        # Medir otra vez el mismo pulso reemplaza la medida anterior
        lista = [p for p in self.puntos[servo] if abs(p[0] - us) >= 5]
        lista.append([float(us), float(angulo)])
        self.puntos[servo] = sorted(lista)
        self._guardar()

    def borrar(self, servo, indice):
        del self.puntos[servo][indice]
        self._guardar()

    def fijar_limite(self, servo, extremo, us):
        """extremo 0 = mínimo, 1 = máximo; us None lo borra."""
        nuevo = list(self.limites[servo])
        nuevo[extremo] = None if us is None else float(us)
        if None not in nuevo and nuevo[0] >= nuevo[1]:
            raise ValueError("el mínimo tiene que ser menor que el máximo")
        self.limites[servo] = nuevo
        self._guardar()

    def acotar(self, servo, us):
        minimo, maximo = self.limites[servo]
        if minimo is not None:
            us = max(us, minimo)
        if maximo is not None:
            us = min(us, maximo)
        return us

    def ajuste(self, servo):
        propio = ajustar(self.puntos[servo])
        if propio or servo != "hombro_der":
            return propio
        izq = ajustar(self.puntos["hombro_izq"])
        if not izq:
            return None
        # ángulo = m·us_izq + b con us_izq = 2·C − us_der
        return {"pendiente": -izq["pendiente"],
                "corte": izq["corte"] + 2 * izq["pendiente"] * CENTRO_ESPEJO,
                "error_max": izq["error_max"], "espejo": True}

    def resumen(self):
        return {s: {"puntos": self.puntos[s], "ajuste": self.ajuste(s), "limites": self.limites[s]}
                for s in SERVOS}

    def _guardar(self):
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        temporal = self.ruta.with_suffix(".tmp")
        datos = {"puntos": self.puntos, "limites": self.limites, "notas": self.notas}
        temporal.write_text(json.dumps(datos, indent=2) + "\n", encoding="utf-8")
        os.replace(temporal, self.ruta)
