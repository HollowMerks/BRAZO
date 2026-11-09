#!/usr/bin/env python3
"""Convierte las piezas del modelo 3D (3MF) en mallas listas para la vista 3D.

Fuente: «Robotic Arm with Servo & Arduino» (Emre Kalem, MakerWorld), el diseño
que imprimió el usuario. El 3MF trae las piezas sueltas en placas de impresión,
no armadas: aquí cada pieza se lleva al marco de su eslabón con medidas tomadas
del propio modelo el 30/10 (centros de agujeros y ventanas, ver README).

Marcos (mm, Y hacia arriba, como en three.js):
  caja      origen en la mesa bajo el eje de giro; el lado largo de la caja hacia -X
            (con giro 0 el brazo mira hacia el extremo redondo, como está armado)
  torreta   gira con la base; origen en el eje de giro, a ras de su plato
  brazo     origen en el eje del hombro; tramo recto hacia +Y, doblez hacia +X
  antebrazo origen en el eje del codo; +X hacia el eje de la muñeca
  muñeca    (Bilek) origen en el pasador de la muñeca; +X hacia la mano, Z = el pasador
  mano      origen en el eje del giro de muñeca; +X hacia los dedos, +Y hacia el servo
            de la garra (va arriba), Z hacia donde abren los dedos
  dedos     cada pieza de la garra con el origen en su pivote y el brazo hacia +X

Formato .bin (little endian): "BRZ1", uint32 vértices, uint32 triángulos,
float32[3·v] posiciones, uint32[3·t] índices.

Uso: python3 herramientas/exportar_modelo.py [ruta.3mf]
"""
import json
import re
import struct
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
FUENTE = RAIZ.parent / "modelo" / "fuente" / "brazo.3mf"
SALIDA = RAIZ / "web" / "modelo"
NS = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
RUTA = "{http://schemas.microsoft.com/3dmanufacturing/production/2015/06}path"

# Medidas en las coordenadas originales de cada pieza (centradas en su caja envolvente)
CAJA_EJE_X = 44.96          # Alt_Kasa: centro del agujero redondo de la torreta
CAJA_ALTO = 70.0
TORRETA_MEDIO_ALTO = 30.0   # Alt_Govde mide 60 de alto
HOMBRO = (-20.05, -93.44)   # Alt_Kol: agujero del hombro (x, z)
CODO = (27.45, 100.83)      # Alt_Kol: agujero del codo (x, z)
ANTEBRAZO_CODO = 66.20      # On_Kol: agujero del codo (x)
ANTEBRAZO_MUNECA = -73.79   # On_Kol: agujero de la muñeca (x)
BILEK_PASADOR = 7.46        # Bilek: agujero del pasador (y), atraviesa los brazos de la U a lo largo de x
MANO_EJE_Z = 1.5            # El_Ust: altura (z) del eje del servo de giro de muñeca y del medio de la garra
MANO_INF_Z = -7.5           # El: la placa de abajo queda 7,5 mm bajo ese eje
# Agujero de pivote de cada pieza de la garra (x, y en sus coordenadas propias)
PIVOTE_ENGRANAJE = (-8.06, 0.0)   # Parmak_Disli: centro del engranaje
PIVOTE_ESLABON = (-10.05, 0.0)    # Parmak
PIVOTE_DEDO = (-9.0, -8.16)       # Parmak_2: el agujero que va al brazo del engranaje
EJE_ENGRANAJE = (1.06, -0.12)     # Disli

# Cada transformación es un giro propio (determinante +1), así las caras no se dan vuelta
PIEZAS = [
    ("Alt_Kasa.stl", "caja", lambda x, y, z: (x - CAJA_EJE_X, z + CAJA_ALTO / 2, -y)),
    ("Alt_Govde.stl", "torreta", lambda x, y, z: (-x, z + TORRETA_MEDIO_ALTO, y)),
    ("Alt_Kol.stl", "brazo", lambda x, y, z: (x - HOMBRO[0], z - HOMBRO[1], -y)),
    ("On_Kol.stl", "antebrazo", lambda x, y, z: (ANTEBRAZO_CODO - x, z, y)),
    # Garra (06/11): tres MG90S para muñeca, giro de muñeca y apertura
    ("Bilek.stl", "muneca", lambda x, y, z: (BILEK_PASADOR - y, -z, x)),
    ("El_Ust.stl", "mano_sup", lambda x, y, z: (x, MANO_EJE_Z - z, y)),
    ("El.stl", "mano_inf", lambda x, y, z: (x, z + MANO_INF_Z, -y)),
    ("Parmak_Disli X 2.stl", "dedo_engranaje", lambda x, y, z: (x - PIVOTE_ENGRANAJE[0], z, PIVOTE_ENGRANAJE[1] - y)),
    ("Parmak X 2.stl", "eslabon", lambda x, y, z: (x - PIVOTE_ESLABON[0], z, PIVOTE_ESLABON[1] - y)),
    ("Parmak_2 X 2.stl", "dedo", lambda x, y, z: (x - PIVOTE_DEDO[0], z, PIVOTE_DEDO[1] - y)),
    ("Disli.stl", "engranaje", lambda x, y, z: (x - EJE_ENGRANAJE[0], z, EJE_ENGRANAJE[1] - y)),
]


def nombres(z):
    cfg = z.read("Metadata/model_settings.config").decode()
    res = {}
    for m in re.finditer(r'<object id="(\d+)">(.*?)</object>', cfg, re.S):
        n = re.search(r'key="name" value="([^"]*)"', m.group(2))
        if n:
            res[n.group(1)] = m.group(1)
    return res


def malla(z, objetos, oid):
    """Vértices e índices de la primera malla de un objeto del 3MF."""
    comp = objetos[oid].find(f"{NS}components/{NS}component")
    raiz = ET.fromstring(z.read(comp.get(RUTA).lstrip("/")))
    for obj in raiz.iter(f"{NS}object"):
        if obj.get("id") == comp.get("objectid"):
            v = [(float(e.get("x")), float(e.get("y")), float(e.get("z"))) for e in obj.iter(f"{NS}vertex")]
            t = [(int(e.get("v1")), int(e.get("v2")), int(e.get("v3"))) for e in obj.iter(f"{NS}triangle")]
            return v, t
    raise KeyError(oid)


def escribir(ruta, v, t):
    with open(ruta, "wb") as f:
        f.write(b"BRZ1" + struct.pack("<II", len(v), len(t)))
        f.write(struct.pack(f"<{3 * len(v)}f", *(c for p in v for c in p)))
        f.write(struct.pack(f"<{3 * len(t)}I", *(i for tri in t for i in tri)))


def main():
    fuente = Path(sys.argv[1]) if len(sys.argv) > 1 else FUENTE
    z = zipfile.ZipFile(fuente)
    modelo = ET.fromstring(z.read("3D/3dmodel.model"))
    objetos = {o.get("id"): o for o in modelo.iter(f"{NS}object")}
    ids = nombres(z)
    SALIDA.mkdir(parents=True, exist_ok=True)
    for nombre, archivo, transformar in PIEZAS:
        v, t = malla(z, objetos, ids[nombre])
        v = [transformar(*p) for p in v]
        escribir(SALIDA / f"{archivo}.bin", v, t)
        print(f"{archivo:10} {len(t):6d} triángulos  ({nombre})")

    codo = (CODO[0] - HOMBRO[0], CODO[1] - HOMBRO[1])
    medidas = {
        "hombro_a_codo": [round(codo[0], 2), round(codo[1], 2)],  # con el tramo recto vertical
        "eje_a_eje": round((codo[0] ** 2 + codo[1] ** 2) ** 0.5, 2),
        "codo_a_muneca": round(ANTEBRAZO_CODO - ANTEBRAZO_MUNECA, 2),
        # Tramo recto de la pieza sin cortar y altura (desde el eje del hombro) del
        # corte: el usuario acortó la pieza real cortándola por la mitad del tramo recto
        "brazo_recto": 172.12,
        "corte_brazo": 86.0,
        "caja": {"largo": 210.0, "ancho": 120.0, "alto": CAJA_ALTO},
        # Ventana del servo del hombro en la torreta (centro en X, alto en Y desde el plato)
        # y la cara exterior de cada pared, donde se atornilla
        "servo_hombro": {"x": -19.75, "y": 40.0, "pared": [19.14, 30.7]},
        # Garra, medida el 06/11 sobre las piezas (marco «mano» de la cabecera). El origen de
        # la mano queda a 63,5 mm del pasador: 27,46 hasta la cara de la U donde se atornilla
        # el brazo del servo, y 36 desde ahí hasta el centro de las placas
        "mano": {
            "origen": 63.5,
            # Pivotes del lado de +Z (el otro es su espejo): engranaje y eslabón, 16 mm entre
            # sí como los dos agujeros del dedo; los dos brazos miden 20 mm: paralelogramo
            "engranaje": [19.27, 8.0], "eslabon": [7.95, 19.3], "brazo": 20.0,
            "dedo_angulo": -45.0,          # el dedo queda girado así respecto a la pieza impresa
            "engranaje_servo": [4.0, 5.3],  # eje del servo de la garra (Disli)
            # Ángulo de los brazos: 17,5° = dedos a 1 mm (cerrada), 85° = 29 mm (abierta)
            "cerrada": 17.5, "abierta": 85.0,
        },
    }
    (SALIDA / "piezas.json").write_text(json.dumps({
        "fuente": "Robotic Arm with Servo & Arduino (Emre Kalem, MakerWorld)",
        "piezas": [archivo for _, archivo, _ in PIEZAS],
        "medidas": medidas,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(medidas, ensure_ascii=False))


if __name__ == "__main__":
    main()
