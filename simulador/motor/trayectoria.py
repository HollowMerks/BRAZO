"""Trayectorias coordinadas del hombro y el codo.

Las dos articulaciones empiezan y terminan a la vez, con un perfil de quinto
grado (llegan con velocidad y aceleración nulas: sin tirones). Si en algún
instante el brazo tocaría la mesa o la base, el codo se flexiona lo mínimo
necesario y con antelación, poco a poco; si ni así se puede, el plan se
rechaza indicando cuándo y dónde falla.
"""
import math
from dataclasses import dataclass, field

from .cinematica import holgura

PASO = 0.02      # s entre muestras (= ciclo de control)
INTENTOS = 5     # cada reintento alarga la duración un 30 %


@dataclass
class Plan:
    valido: bool
    motivo: str = ""
    duracion: float = 0.0
    hombro: list = field(default_factory=list)
    codo: list = field(default_factory=list)
    corregido: float = 0.0  # flexión extra máxima del codo, en grados


def duracion_minima(cfg, inicio, fin):
    """La duración más corta que respeta velocidad y aceleración máximas de ambas articulaciones."""
    T = 0.3
    for art, a, b in ((cfg.hombro, inicio[0], fin[0]), (cfg.codo, inicio[1], fin[1])):
        d = abs(b - a)
        # Perfil de quinto grado desde parado: picos de 1,875·d/T y 5,77·d/T²
        T = max(T, 1.875 * d / art.vmax, math.sqrt(5.7735 * d / art.amax))
    return T


def planificar(cfg, pos, vel, destino, duracion=None):
    """Plan desde la pose y velocidad actuales hasta `destino` (hombro, codo)."""
    if not (cfg.hombro.minimo <= destino[0] <= cfg.hombro.maximo
            and cfg.codo.minimo <= destino[1] <= cfg.codo.maximo):
        return Plan(False, "El destino está fuera de los límites de las articulaciones")
    T = max(duracion or 0.0, duracion_minima(cfg, pos, destino))
    piso = min(0.0, holgura(cfg, *pos).mm)  # si ya empieza tocando, que al menos no empeore
    for _ in range(INTENTOS):
        plan, reintentar = _intentar(cfg, pos, vel, destino, T, piso)
        if plan.valido or not reintentar:
            return plan
        T *= 1.3
    return plan


def _intentar(cfg, pos, vel, destino, T, piso):
    """Un intento con duración T. Devuelve (plan, conviene_reintentar_más_lento)."""
    n = max(2, math.ceil(T / PASO))
    T = n * PASO
    ch = _quintica(pos[0], vel[0], 0.0, destino[0], T)
    cc = _quintica(pos[1], vel[1], 0.0, destino[1], T)
    hombro = [_valor(ch, i * PASO) for i in range(n + 1)]
    codo = [_valor(cc, i * PASO) for i in range(n + 1)]

    for i, h in enumerate(hombro):
        if not cfg.hombro.minimo - 1e-6 <= h <= cfg.hombro.maximo + 1e-6:
            return Plan(False, f"A los {i * PASO:.1f} s el hombro pasaría su límite"), False

    elegido, fallo = None, 0
    for sentido in (1, -1):
        necesidad = []
        for i, (h, c) in enumerate(zip(hombro, codo)):
            extra = _flexion_necesaria(cfg, h, c, sentido, piso)
            if extra is None:
                fallo = max(fallo, i)
                break
            necesidad.append(extra)
        else:
            if elegido is None or max(necesidad) < max(elegido[1]):
                elegido = (sentido, necesidad)
    if elegido is None:
        donde = holgura(cfg, hombro[fallo], codo[fallo]).donde
        return Plan(False, f"A los {fallo * PASO:.1f} s quedaría {donde}, aunque el codo se flexione al máximo"), False

    sentido, necesidad = elegido
    extra = _envolvente(necesidad, 0.6 * cfg.codo.vmax * PASO)
    extra[0] = 0.0  # el codo no puede saltar en el primer instante
    codo = [min(max(c + sentido * e, cfg.codo.minimo), cfg.codo.maximo) for c, e in zip(codo, extra)]

    for i, (h, c) in enumerate(zip(hombro, codo)):
        hg = holgura(cfg, h, c)
        if hg.mm < piso - 1e-6:
            return Plan(False, f"A los {i * PASO:.1f} s quedaría {hg.donde}"), True
    for serie, art, nombre in ((hombro, cfg.hombro, "hombro"), (codo, cfg.codo, "codo")):
        mayor = max(abs(b - a) for a, b in zip(serie, serie[1:])) / PASO
        if mayor > art.vmax * 1.05:
            return Plan(False, f"El {nombre} tendría que ir demasiado rápido"), True

    corregido = max(extra)
    motivo = f"El codo se flexiona hasta {corregido:.0f}° extra para esquivar" if corregido >= 0.5 else ""
    return Plan(True, motivo, T, hombro, codo, corregido), False


def _quintica(p0, v0, a0, p1, T):
    """Coeficientes del polinomio de grado 5 que va de (p0, v0, a0) a (p1, 0, 0) en T segundos."""
    h = p1 - p0
    return (p0, v0, a0 / 2,
            (20 * h - 12 * v0 * T - 3 * a0 * T ** 2) / (2 * T ** 3),
            (-30 * h + 16 * v0 * T + 3 * a0 * T ** 2) / (2 * T ** 4),
            (12 * h - 6 * v0 * T - a0 * T ** 2) / (2 * T ** 5))


def _valor(c, t):
    return c[0] + t * (c[1] + t * (c[2] + t * (c[3] + t * (c[4] + t * c[5]))))


def _flexion_necesaria(cfg, h, c, sentido, piso):
    """Mínima flexión extra del codo (en `sentido`) para que la pose no toque nada; None si no existe."""
    def sirve(e):
        return holgura(cfg, h, c + sentido * e).mm >= piso

    if sirve(0.0):
        return 0.0
    limite = cfg.codo.maximo if sentido > 0 else cfg.codo.minimo
    rango = (limite - c) * sentido
    anterior, e = 0.0, 0.0
    while e < rango:
        e = min(e + 2.0, rango)
        if sirve(e):
            bajo, alto = anterior, e
            for _ in range(6):
                medio = (bajo + alto) / 2
                if sirve(medio):
                    alto = medio
                else:
                    bajo = medio
            return alto
        anterior = e
    return None


def _envolvente(necesidad, pendiente):
    """Curva mínima que cubre `necesidad` sin cambiar más de `pendiente` por muestra, suavizada.

    La pasada hacia atrás hace que el codo empiece a flexionarse antes de que
    haga falta, poco a poco, en lugar de corregir de golpe.
    """
    e = list(necesidad)
    for i in range(1, len(e)):
        e[i] = max(e[i], e[i - 1] - pendiente)
    for i in range(len(e) - 2, -1, -1):
        e[i] = max(e[i], e[i + 1] - pendiente)
    k = 4
    suave = []
    for i in range(len(e)):
        ventana = e[max(0, i - k):i + k + 1]
        suave.append(sum(ventana) / len(ventana))
    return [max(s, nec) for s, nec in zip(suave, necesidad)]
