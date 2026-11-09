"""Rutinas: una serie de pasos que el brazo repite en orden (etapa C).

Cada paso es una pose: cualquiera de hombro, codo, giro, muneca, giro_muneca y
garra (lo que falte queda como está), más una espera opcional. Al ejecutar un
paso se mueven primero el giro y la mano y después el brazo, siempre con el
mismo control que los joysticks: los planes se comprueban contra la mesa y la
caja, y si algo se detiene la rutina se corta y dice dónde.

Así, para no rozar nada, conviene un paso por cosa: subir, después girar,
después bajar. Las rutinas se guardan en datos/rutinas/<nombre>.json.
"""
import json
import math
import os
import re
import threading
import time
from dataclasses import replace
from pathlib import Path

from .cinematica import holgura
from .control import AUXILIARES
from .trayectoria import planificar

BRAZO = ("hombro", "codo")
CAMPOS = BRAZO + tuple(AUXILIARES)
MUESTRAS_AUXILIARES = 12  # puntos que se revisan al comprobar un giro o un movimiento de la mano


def nombre_valido(nombre):
    nombre = str(nombre).strip()
    if not re.fullmatch(r"[\w\-]{1,40}", nombre):
        raise ValueError("Nombre de rutina: letras, números, - y _ (hasta 40)")
    return nombre


def limpiar_pasos(pasos):
    """Valida el formato de los pasos y los devuelve normalizados."""
    if not isinstance(pasos, list) or not pasos:
        raise ValueError("La rutina no tiene pasos")
    if len(pasos) > 200:
        raise ValueError("Demasiados pasos (máximo 200)")
    limpios = []
    for i, paso in enumerate(pasos, 1):
        if not isinstance(paso, dict):
            raise ValueError(f"Paso {i}: formato inválido")
        limpio = {"nombre": str(paso.get("nombre") or f"Paso {i}")[:60]}
        for campo in CAMPOS + ("espera", "duracion"):
            if paso.get(campo) is not None:
                valor = float(paso[campo])
                if not math.isfinite(valor):
                    raise ValueError(f"Paso {i}: {campo} inválido")
                limpio[campo] = valor
        if ("hombro" in limpio) != ("codo" in limpio):
            raise ValueError(f"Paso {i}: hombro y codo van juntos")
        if not 0 <= limpio.get("espera", 0) <= 60:
            raise ValueError(f"Paso {i}: la espera va de 0 a 60 s")
        if "duracion" in limpio and not 0 < limpio["duracion"] <= 60:
            raise ValueError(f"Paso {i}: la duración va de 0 a 60 s")
        if not any(c in limpio for c in CAMPOS) and "espera" not in limpio:
            raise ValueError(f"Paso {i}: no mueve nada ni espera")
        limpios.append(limpio)
    return limpios


def comprobar(cfg, pos, pasos):
    """Recorre la rutina sin mover nada. Devuelve (problemas, segundos estimados)."""
    problemas, total = [], 0.0
    for i, paso in enumerate(pasos, 1):
        nombre = paso["nombre"]
        cambios = {k: paso[k] for k in AUXILIARES if k in paso}
        for k, v in cambios.items():
            art = getattr(cfg, AUXILIARES[k])
            if not art.minimo - 1e-6 <= v <= art.maximo + 1e-6:
                problemas.append(f"Paso {i} ({nombre}): {k} fuera de sus límites")
        if cambios and any(k != "giro" for k in cambios) and not cfg.garra_montada:
            problemas.append(f"Paso {i} ({nombre}): mueve la mano, pero la garra no está montada")
        if cambios:
            # El giro y la mano van primero, con el brazo quieto: se revisa el recorrido
            inicio = {k: getattr(cfg, k) for k in cambios}
            for n in range(1, MUESTRAS_AUXILIARES + 1):
                t = n / MUESTRAS_AUXILIARES
                intermedia = replace(cfg, **{k: inicio[k] + (v - inicio[k]) * t for k, v in cambios.items()})
                hg = holgura(intermedia, *pos)
                if hg.mm < min(-0.5, holgura(cfg, *pos).mm):
                    problemas.append(f"Paso {i} ({nombre}): al mover {', '.join(cambios)} quedaría {hg.donde}")
                    break
            mas_lento = max(abs(v - inicio[k]) / getattr(cfg, AUXILIARES[k]).vmax for k, v in cambios.items())
            total += mas_lento + 0.3
            cfg = replace(cfg, **cambios)
        if "hombro" in paso:
            plan = planificar(cfg, list(pos), [0.0, 0.0], (paso["hombro"], paso["codo"]), paso.get("duracion"))
            if not plan.valido:
                problemas.append(f"Paso {i} ({nombre}): {plan.motivo}")
            else:
                pos = (plan.hombro[-1], plan.codo[-1])
                total += plan.duracion
        total += paso.get("espera", 0)
    return problemas, total


class Rutinas:
    def __init__(self, control, carpeta):
        self.control = control
        self.carpeta = Path(carpeta)
        self._hilo = None
        self._parar = threading.Event()
        self._estado = {"activa": False, "nombre": "", "paso": 0, "total": 0, "descripcion": "", "aviso": ""}
        control.rutina = self.estado

    # --- archivos ---

    def lista(self):
        return sorted(p.stem for p in self.carpeta.glob("*.json"))

    def leer(self, nombre):
        ruta = self.carpeta / f"{nombre_valido(nombre)}.json"
        if not ruta.exists():
            raise ValueError(f"No existe la rutina «{nombre}»")
        return json.loads(ruta.read_text(encoding="utf-8"))["pasos"]

    def guardar(self, nombre, pasos):
        nombre, pasos = nombre_valido(nombre), limpiar_pasos(pasos)
        self.carpeta.mkdir(parents=True, exist_ok=True)
        ruta = self.carpeta / f"{nombre}.json"
        temporal = ruta.with_suffix(".tmp")
        temporal.write_text(json.dumps({"pasos": pasos}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temporal, ruta)
        return pasos

    def borrar(self, nombre):
        ruta = self.carpeta / f"{nombre_valido(nombre)}.json"
        if ruta.exists():
            ruta.unlink()

    # --- comprobar y ejecutar ---

    def comprobar(self, pasos):
        with self.control._lock:
            cfg, pos = self.control.cfg, tuple(self.control.pos)
        problemas, segundos = comprobar(cfg, pos, limpiar_pasos(pasos))
        return {"problemas": problemas, "segundos": round(segundos, 1)}

    def estado(self):
        return dict(self._estado)

    def ejecutar(self, nombre, pasos):
        if self._hilo is not None and self._hilo.is_alive():
            raise ValueError("Ya hay una rutina en marcha")
        pasos = limpiar_pasos(pasos)
        revision = self.comprobar(pasos)
        if revision["problemas"]:
            raise ValueError(revision["problemas"][0])
        self._parar.clear()
        self._estado = {"activa": True, "nombre": nombre, "paso": 0, "total": len(pasos), "descripcion": "", "aviso": ""}
        self._hilo = threading.Thread(target=self._correr, args=(pasos,), daemon=True, name="rutina")
        self._hilo.start()
        return revision

    def detener(self):
        if self._hilo is not None and self._hilo.is_alive():
            self._parar.set()
            self._hilo.join(timeout=2)
        self.control.detener()

    def _correr(self, pasos):
        try:
            for i, paso in enumerate(pasos, 1):
                self._estado.update(paso=i, descripcion=paso["nombre"])
                self._paso(paso)
            self._estado.update(activa=False, aviso="Terminada")
        except _Corte as e:
            self.control.detener()
            self._estado.update(activa=False, aviso=str(e))

    def _paso(self, paso):
        ctl = self.control
        for k in AUXILIARES:
            if k in paso:
                try:
                    objetivo = ctl.mover_auxiliar(k, paso[k])
                except ValueError as e:
                    raise _Corte(f"Paso {self._estado['paso']}: {e}") from None
                self._esperar(lambda k=k, o=objetivo: getattr(ctl.cfg, k) == o and ctl.velocidades[k] == 0,
                              lambda k=k, o=objetivo: ctl.objetivos[k] != o, f"mover {k}")
        if "hombro" in paso:
            destino = (paso["hombro"], paso["codo"])
            r = ctl.mover(destino, paso.get("duracion"))
            if not r["valido"]:
                raise _Corte(f"Paso {self._estado['paso']}: {r['motivo']}")
            final = r["destino"]
            self._esperar(lambda: ctl.plan is None, lambda: False, "llegar")
            if any(abs(p - f) > 0.05 for p, f in zip(ctl.pos, final)):
                raise _Corte(f"Paso {self._estado['paso']}: interrumpido antes de llegar")
        fin = time.monotonic() + paso.get("espera", 0)
        while time.monotonic() < fin:
            if self._parar.wait(0.05):
                raise _Corte("Detenida")

    def _esperar(self, listo, bloqueado, que, limite=60):
        fin = time.monotonic() + limite
        while not listo():
            if self._parar.wait(0.02):
                raise _Corte("Detenida")
            if bloqueado():
                raise _Corte(f"Paso {self._estado['paso']}: al {que}, {self.control.aviso or 'se detuvo'}")
            if time.monotonic() > fin:
                raise _Corte(f"Paso {self._estado['paso']}: tardó demasiado en {que}")


class _Corte(Exception):
    pass
