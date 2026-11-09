"""Configuración del brazo: geometría, límites y velocidades.

Unidades: milímetros, grados y segundos. Origen en la mesa, justo debajo del
eje del hombro; x hacia el frente del brazo, y hacia arriba.

La pieza gris tiene un tramo recto (desde el eje del hombro) y un tramo
inclinado hacia adelante que termina en el eje del codo.

Las medidas salen del modelo 3D que imprimió el usuario (ver
herramientas/exportar_modelo.py). La caja azul no gira: la torreta, con los
hombros, gira sobre ella (`giro`), así que lo que el brazo tiene debajo en su
plano depende de ese giro (cinematica.base_en_plano).

Los ángulos son MECÁNICOS, no los del servo (esos se calibran en la etapa B):
  hombro: inclinación del tramo recto de la pieza gris respecto a la mesa
          (0 = horizontal hacia el frente, 90 = vertical). Se mide apoyando el
          inclinómetro del celular en esa cara plana.
  codo:   giro del antebrazo respecto a ese tramo recto (0 = siguiendo su
          línea, -90 = perpendicular hacia adelante).
"""
import json
import math
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Articulacion:
    minimo: float
    maximo: float
    vmax: float  # grados/s
    amax: float  # grados/s²


ARTICULACIONES = ("hombro", "codo", "torreta", "lim_muneca", "lim_giro_muneca", "lim_garra")


@dataclass
class Config:
    # Del modelo 3D (30/10). El doblez es la intersección de las líneas
    # centrales de los dos tramos. En el modelo el tramo recto mide 172,12 (eje a
    # eje 200); el usuario cortó la pieza real por la mitad de ese tramo: unos
    # 50 mm menos, ESTIMADO en sus fotos del 30/10 (falta medirlo con regla)
    altura_hombro: float = 110      # caja de 70 + 40 de la torreta, apoyada en la caja (foto del 30/10)
    brazo_recto: float = 122.12     # eje del hombro → doblez
    brazo_inclinado: float = 52.41  # doblez → eje del codo
    brazo_angulo: float = 65        # cuánto se inclina ese tramo hacia adelante
    largo_antebrazo: float = 140    # eje del codo → eje de la muñeca (la «punta»)
    grosor_brazo: float = 50
    grosor_antebrazo: float = 40
    # Caja azul: un extremo es un semicírculo centrado en el eje de giro
    caja_largo: float = 210
    caja_ancho: float = 120
    base_alto: float = 70
    # El eje del hombro queda detrás del eje de giro. HIPÓTESIS: el eje del servo
    # a ~10 mm del centro de su ventana (19,75 mm), del lado del cable
    hombro_atras_giro: float = 9.75
    # Torreta respecto a la caja; 0 = brazo hacia el extremo redondo (foto del 30/10).
    # Es la pose inicial del giro: en marcha lo mueve el control, no se escribe a mano
    giro: float = 0
    # Servo de giro: pulso con la torreta en 0 y µs por grado (negativo = al revés).
    # Sin calibrar: 11,11 es el valor nominal de un servo de 180° (2000 µs de recorrido)
    giro_centro_us: float = 1500
    giro_us_por_grado: float = 11.11
    margen: float = 15
    # Garra del modelo 3D (06/11), medida sobre las piezas: el pasador de la muñeca está
    # en la «punta» (eje de la muñeca). Con la garra puesta, la mano cuenta en los choques
    garra_montada: bool = True
    mano_base: float = 27.5     # pasador → cara de la U donde se atornilla el giro de muñeca
    mano_palma: float = 88.5    # pasador → frente de las placas de la mano
    mano_largo: float = 144     # pasador → puntas de los dedos (cerrada; abierta quedan más atrás)
    mano_radio: float = 27      # del eje al borde del servo de la garra, que va arriba
    # Mitad del ancho de dedos y brazos, cerrada y abierta: con la mano girada 90°
    # queda en el plano del brazo
    garra_ancho_cerrada: float = 30.5
    garra_ancho_abierta: float = 44.5
    garra_apertura: float = 29  # mm entre las puntas de los dedos, del todo abierta
    # Pose de la mano. Como el giro, la mueve el control. Muñeca: ángulo de la mano
    # respecto al antebrazo en el plano del brazo (90 = doblada hacia arriba). La pose
    # plegada de inicio solo es válida con la muñeca doblada: recta, los dedos quedarían
    # bajo la mesa. Giro de muñeca: sobre su propio eje. Garra: 0 = cerrada, 100 = abierta
    muneca: float = 90
    giro_muneca: float = 0
    garra: float = 0
    hombro: Articulacion = field(default_factory=lambda: Articulacion(30, 135, 35, 70))
    codo: Articulacion = field(default_factory=lambda: Articulacion(-150, -20, 35, 70))
    # ±54° lo eligió el usuario el 31/10: 900-2100 µs con la escala nominal, los mismos
    # topes del firmware. 10°/s y 20°/s² quedan por debajo de sus 120 µs/s y 240 µs/s²
    torreta: Articulacion = field(default_factory=lambda: Articulacion(-54, 54, 10, 20))
    # Los MG90S son de 180°: ±90 desde el centro. Garra en % por segundo
    lim_muneca: Articulacion = field(default_factory=lambda: Articulacion(-90, 90, 60, 120))
    lim_giro_muneca: Articulacion = field(default_factory=lambda: Articulacion(-90, 90, 60, 120))
    lim_garra: Articulacion = field(default_factory=lambda: Articulacion(0, 100, 100, 300))
    # Pose física del 28/10: tramo recto vertical, antebrazo horizontal hacia adelante
    reposo_hombro: float = 90
    reposo_codo: float = -91

    def a_dict(self):
        return asdict(self)

    @classmethod
    def desde_dict(cls, datos):
        """Crea una configuración desde un dict parcial; lo que falte toma el valor por defecto."""
        base = asdict(cls())
        for clave, valor in datos.items():
            if clave not in base:
                continue
            if isinstance(base[clave], dict):
                if not isinstance(valor, dict):
                    raise ValueError(f"{clave} debe ser un objeto")
                for sub, v in valor.items():
                    if sub in base[clave]:
                        base[clave][sub] = float(v)
            elif isinstance(base[clave], bool):
                base[clave] = valor if isinstance(valor, bool) else str(valor).lower() in ("1", "true", "si", "sí", "on")
            else:
                base[clave] = float(valor)
        articulaciones = {k: Articulacion(**base.pop(k)) for k in ARTICULACIONES}
        return cls(**base, **articulaciones)

    def errores(self):
        """Lista de problemas que impiden usar esta configuración (vacía si está bien)."""
        e = []
        planos = {k: v for k, v in asdict(self).items() if not isinstance(v, dict)}
        for nombre in ARTICULACIONES:
            for sub, v in asdict(getattr(self, nombre)).items():
                planos[f"{nombre}.{sub}"] = v
        for nombre, valor in planos.items():
            if not math.isfinite(valor):
                e.append(f"{nombre} no es un número válido")
        if e:
            return e
        for nombre in ("altura_hombro", "brazo_recto", "largo_antebrazo", "grosor_brazo",
                       "grosor_antebrazo", "caja_ancho", "base_alto"):
            if getattr(self, nombre) <= 0:
                e.append(f"{nombre} debe ser mayor que 0")
        if self.caja_largo < self.caja_ancho / 2:
            e.append("caja_largo no puede ser menor que la mitad de caja_ancho")
        if not -180 <= self.giro <= 180:
            e.append("giro debe estar entre -180 y 180")
        if self.brazo_inclinado < 0:
            e.append("brazo_inclinado no puede ser negativo")
        if not -90 <= self.brazo_angulo <= 90:
            e.append("brazo_angulo debe estar entre -90 y 90")
        if self.margen < 0:
            e.append("margen no puede ser negativo")
        if self.giro_us_por_grado == 0:
            e.append("giro_us_por_grado no puede ser 0")
        for nombre in ("mano_base", "mano_palma", "mano_largo", "mano_radio", "garra_ancho_cerrada",
                       "garra_ancho_abierta", "garra_apertura"):
            if getattr(self, nombre) <= 0:
                e.append(f"{nombre} debe ser mayor que 0")
        if not self.mano_base < self.mano_palma < self.mano_largo:
            e.append("la mano debe cumplir mano_base < mano_palma < mano_largo")
        for valor, lim in (("muneca", "lim_muneca"), ("giro_muneca", "lim_giro_muneca"), ("garra", "lim_garra")):
            art = getattr(self, lim)
            if not art.minimo - 1e-6 <= getattr(self, valor) <= art.maximo + 1e-6:
                e.append(f"{valor} está fuera de sus límites")
        if not (0 <= self.lim_garra.minimo and self.lim_garra.maximo <= 100):
            e.append("los límites de la garra van de 0 a 100 %")
        for nombre in ARTICULACIONES:
            art = getattr(self, nombre)
            if art.minimo >= art.maximo:
                e.append(f"{nombre}: el mínimo debe ser menor que el máximo")
            if art.vmax <= 0 or art.amax <= 0:
                e.append(f"{nombre}: velocidad y aceleración deben ser mayores que 0")
        if not self.hombro.minimo <= self.reposo_hombro <= self.hombro.maximo:
            e.append("el reposo del hombro está fuera de sus límites")
        if not self.codo.minimo <= self.reposo_codo <= self.codo.maximo:
            e.append("el reposo del codo está fuera de sus límites")
        return e


def cargar(ruta):
    ruta = Path(ruta)
    if ruta.exists():
        return Config.desde_dict(json.loads(ruta.read_text(encoding="utf-8")))
    return Config()


def guardar(cfg, ruta):
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(".tmp")
    temporal.write_text(json.dumps(cfg.a_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporal, ruta)
