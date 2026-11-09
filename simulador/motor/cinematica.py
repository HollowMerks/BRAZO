"""Cinemática 2D del brazo (hombro + codo) y comprobación de choques.

La pieza gris es un tramo recto (eje del hombro → doblez) más un tramo
inclinado hacia adelante (doblez → eje del codo). Cada pieza se trata como un
tubo de su grosor alrededor de su línea central.
Contra una mesa plana, un tramo recto solo puede tocarla por uno de sus
extremos, así que basta comprobar los puntos (hombro, doblez, codo y punta).
Contra la base se mide la distancia real de cada tramo a un rectángulo: la
parte de la caja azul que queda bajo el plano del brazo, que depende del giro
de la torreta (base_en_plano).

Con la garra montada, la mano sigue al antebrazo desde el pasador de la muñeca
en tres tubos: la U de la muñeca, la palma (con el servo de la garra arriba) y
los dedos. Su grosor en el plano del brazo depende del giro de muñeca: girada
90°, el ancho de dedos y brazos queda en el plano.
"""
import functools
import math
from dataclasses import dataclass

# Lo más ancho del brazo que puede bajar hacia la caja: la horquilla del
# antebrazo junto al codo (modelo 3D). Se usa para ver qué parte de la caja
# queda bajo el brazo cuando la torreta está girada.
ANCHO_LATERAL = 56
RADIO_MUNECA = 13  # media U de la muñeca en el plano del brazo (Bilek, 25 mm)
MEDIO_DEDO = 6     # mitad del alto de dedos y brazos de la garra (12 mm)


@dataclass
class Holgura:
    mm: float    # espacio libre ya descontados grosor y margen; negativo = choque
    donde: str   # qué parte queda más cerca y de qué


def puntos(cfg, hombro, codo):
    """Posición (x, y) en mm de cada punto del brazo para unos ángulos mecánicos."""
    a1 = math.radians(hombro)
    a_incl = math.radians(hombro - cfg.brazo_angulo)  # el tramo inclinado gira hacia adelante
    a2 = math.radians(hombro + codo)
    h = (0.0, cfg.altura_hombro)
    d = (h[0] + cfg.brazo_recto * math.cos(a1), h[1] + cfg.brazo_recto * math.sin(a1))
    c = (d[0] + cfg.brazo_inclinado * math.cos(a_incl), d[1] + cfg.brazo_inclinado * math.sin(a_incl))
    p = (c[0] + cfg.largo_antebrazo * math.cos(a2), c[1] + cfg.largo_antebrazo * math.sin(a2))
    pts = {"hombro": h, "doblez": d, "codo": c, "punta": p}
    if cfg.garra_montada:
        a3 = a2 + math.radians(cfg.muneca)
        u = (math.cos(a3), math.sin(a3))
        for nombre, largo in (("base_mano", cfg.mano_base), ("palma", cfg.mano_palma), ("dedos", cfg.mano_largo)):
            pts[nombre] = (p[0] + largo * u[0], p[1] + largo * u[1])
    return pts


def radios_mano(cfg):
    """Grosor (radio) de la palma y de los dedos en el plano del brazo."""
    r = abs(math.sin(math.radians(cfg.giro_muneca)))
    abierta = min(max(cfg.garra / 100, 0.0), 1.0)
    ancho = cfg.garra_ancho_cerrada + (cfg.garra_ancho_abierta - cfg.garra_ancho_cerrada) * abierta
    palma = max(cfg.mano_radio, r * ancho)
    dedos = max(MEDIO_DEDO, (1 - r) * MEDIO_DEDO + r * ancho)
    return palma, dedos


def eslabon(cfg):
    """Largo de eje a eje (hombro → codo) y cuántos grados queda esa línea por debajo del tramo recto."""
    a = math.radians(cfg.brazo_angulo)
    largo_x = cfg.brazo_recto + cfg.brazo_inclinado * math.cos(a)
    largo_y = cfg.brazo_inclinado * math.sin(a)
    return math.hypot(largo_x, largo_y), math.degrees(math.atan2(largo_y, largo_x))


def holgura(cfg, hombro, codo):
    """Espacio libre mínimo entre el brazo y la mesa o la base."""
    p = puntos(cfg, hombro, codo)
    r1 = cfg.grosor_brazo / 2
    r2 = cfg.grosor_antebrazo / 2
    desde, hasta = base_en_plano(cfg)
    base = (desde, 0.0, hasta, cfg.base_alto)
    candidatos = [
        (p["doblez"][1] - r1, "el brazo contra la mesa"),
        (p["codo"][1] - r1, "el codo contra la mesa"),
        (p["punta"][1] - r2, "la punta contra la mesa"),
        # El tramo hombro → doblez nace sobre la base: no se compara con ella
        (_dist_segmento_rect(p["doblez"], p["codo"], base) - r1, "el brazo contra la base"),
        (_dist_segmento_rect(p["codo"], p["punta"], base) - r2, "el antebrazo contra la base"),
    ]
    if cfg.garra_montada:
        rp, rd = radios_mano(cfg)
        candidatos += [
            (p["base_mano"][1] - RADIO_MUNECA, "la muñeca contra la mesa"),
            (min(p["base_mano"][1], p["palma"][1]) - rp, "la mano contra la mesa"),
            (p["dedos"][1] - rd, "la garra contra la mesa"),
            (_dist_segmento_rect(p["punta"], p["base_mano"], base) - RADIO_MUNECA, "la muñeca contra la base"),
            (_dist_segmento_rect(p["base_mano"], p["palma"], base) - rp, "la mano contra la base"),
            (_dist_segmento_rect(p["palma"], p["dedos"], base) - rd, "la garra contra la base"),
        ]
    mm, donde = min(candidatos)
    return Holgura(mm - cfg.margen, donde)


def base_en_plano(cfg):
    """Qué tramo de la caja queda bajo el brazo: (desde, hasta) en x, con el eje del hombro en 0."""
    return _base_en_plano(cfg.caja_largo, cfg.caja_ancho, cfg.giro, cfg.hombro_atras_giro)


@functools.lru_cache(maxsize=64)
def _base_en_plano(largo, ancho, giro, atras):
    # Contorno de la caja visto desde arriba, con el eje de giro en el origen.
    # Con giro 0 el brazo mira hacia +x (como está armado): el semicírculo queda
    # delante y el lado largo detrás
    r = ancho / 2
    contorno = [(r * math.cos(a), r * math.sin(a)) for a in (-math.pi / 2 + math.pi * k / 32 for k in range(33))]
    contorno += [(r - largo, r), (r - largo, -r)]
    g = math.radians(giro)
    u = (math.cos(g), math.sin(g))  # dirección del brazo
    n = (-u[1], u[0])
    franja = _recortar(_recortar(contorno, n, ANCHO_LATERAL / 2), (-n[0], -n[1]), ANCHO_LATERAL / 2)
    s = [p[0] * u[0] + p[1] * u[1] for p in franja]
    # El hombro está `atras` mm detrás del eje de giro
    return min(s) + atras, max(s) + atras


def _recortar(poligono, n, w):
    """La parte de un polígono convexo con p·n <= w."""
    res = []
    for i, p in enumerate(poligono):
        q = poligono[(i + 1) % len(poligono)]
        dp = p[0] * n[0] + p[1] * n[1] - w
        dq = q[0] * n[0] + q[1] * n[1] - w
        if dp <= 0:
            res.append(p)
        if (dp <= 0) != (dq <= 0):
            t = dp / (dp - dq)
            res.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
    return res


def dentro_de_limites(cfg, hombro, codo, tolerancia=1e-6):
    return (cfg.hombro.minimo - tolerancia <= hombro <= cfg.hombro.maximo + tolerancia
            and cfg.codo.minimo - tolerancia <= codo <= cfg.codo.maximo + tolerancia)


def inversa(cfg, x, y, codo_actual):
    """Ángulos que llevan la punta a (x, y) con el codo doblado hacia el mismo lado que ahora.

    Devuelve None si el punto queda fuera del alcance.
    """
    l1, desvio = eslabon(cfg)
    l2 = cfg.largo_antebrazo
    X, Y = x, y - cfg.altura_hombro
    d = (X * X + Y * Y - l1 * l1 - l2 * l2) / (2 * l1 * l2)
    if not -1.0 <= d <= 1.0:
        return None
    # Ángulos respecto a la línea eje a eje; luego se pasa al tramo recto
    relativo = codo_actual + desvio
    q2 = math.acos(d) * (-1 if relativo < 0 else 1)
    q1 = math.atan2(Y, X) - math.atan2(l2 * math.sin(q2), l1 + l2 * math.cos(q2))
    return _normalizar(math.degrees(q1) + desvio), math.degrees(q2) - desvio


def _normalizar(angulo):
    return (angulo + 180.0) % 360.0 - 180.0


def _dist_punto_rect(p, r):
    x0, y0, x1, y1 = r
    return math.hypot(max(x0 - p[0], 0.0, p[0] - x1), max(y0 - p[1], 0.0, p[1] - y1))


def _dist_punto_segmento(p, a, b):
    vx, vy = b[0] - a[0], b[1] - a[1]
    largo2 = vx * vx + vy * vy
    t = 0.0 if largo2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / largo2))
    return math.hypot(p[0] - (a[0] + t * vx), p[1] - (a[1] + t * vy))


def _se_cruzan(a, b, c, d):
    def lado(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    return ((lado(a, b, c) > 0) != (lado(a, b, d) > 0)
            and (lado(c, d, a) > 0) != (lado(c, d, b) > 0))


def _dist_segmento_rect(a, b, r):
    x0, y0, x1, y1 = r
    if _dist_punto_rect(a, r) == 0 or _dist_punto_rect(b, r) == 0:
        return 0.0
    esquinas = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    for i in range(4):
        if _se_cruzan(a, b, esquinas[i], esquinas[(i + 1) % 4]):
            return 0.0
    return min(_dist_punto_rect(a, r), _dist_punto_rect(b, r),
               *(_dist_punto_segmento(e, a, b) for e in esquinas))
