"""Bucle de control simulado a 50 Hz.

Sigue los planes de movimiento, los joysticks y las paradas, y en cada ciclo
comprueba que el brazo no toque la mesa ni la base. En la etapa B este mismo
bucle enviará cada pose al Nano.
"""
import math
import queue
import threading
import time
from dataclasses import replace

from .cinematica import base_en_plano, dentro_de_limites, holgura, inversa, puntos, radios_mano
from .config import Config
from .trayectoria import PASO, planificar

VEL_PUNTA = 80.0      # mm/s de la punta con el joystick a fondo
SIN_JOYSTICK = 0.3    # s sin noticias del joystick → frenar
TOLERANCIA_GIRO = 0.5  # mm: justo en el margen, girar cambia la holgura unas décimas sin importar
# Articulaciones que van solas hacia su objetivo, fuera de los planes de hombro y codo:
# valor en la config → sus límites. Mientras se mueven no cambian hombro ni codo
AUXILIARES = {"giro": "torreta", "muneca": "lim_muneca", "giro_muneca": "lim_giro_muneca", "garra": "lim_garra"}


class Controlador:
    def __init__(self, cfg):
        self._lock = threading.Lock()
        self.cfg = cfg
        self.version = 1
        self.pos = [cfg.reposo_hombro, cfg.reposo_codo]
        self.vel = [0.0, 0.0]
        self.plan = None
        self._plan_i = 0
        self._plan_resumen = None
        self.joy = None     # (órdenes, instante)
        self.aviso = ""
        self._sentido = 1   # hacia dónde se flexionó el codo la última vez
        self._oyentes = set()
        self.salida = None  # con el brazo real habilitado: función(hombro, codo) que lo mueve
        self.real = None    # estado del brazo real para la página (lo llena el puente)
        self.pose_real = None  # función → (hombro, codo) del brazo real según la calibración
        self.objetivos = {k: getattr(cfg, k) for k in AUXILIARES}
        self.velocidades = {k: 0.0 for k in AUXILIARES}
        self.salida_giro = None  # con el servo de giro habilitado: función(giro) que lo mueve
        self.giro_real = None    # función → estado del servo de giro para la página
        self.rutina = None       # función → estado de la rutina en marcha (motor/rutinas.py)

    # --- bucle ---

    def iniciar(self):
        threading.Thread(target=self._bucle, daemon=True, name="control").start()

    def _bucle(self):
        siguiente = time.monotonic()
        ciclo = 0
        while True:
            with self._lock:
                self._paso(PASO)
                pos = tuple(self.pos)
                giro = self.cfg.giro
                estado = self._estado() if ciclo % 2 == 0 else None
            salida = self.salida
            if salida is not None and ciclo % 2 == 0:
                salida(*pos)  # 25 envíos por segundo; el firmware suaviza entre uno y otro
            salida_giro = self.salida_giro
            if salida_giro is not None and ciclo % 2 == 0:
                salida_giro(giro)
            if estado is not None:
                self._publicar(estado)
            ciclo += 1
            siguiente += PASO
            espera = siguiente - time.monotonic()
            if espera > 0:
                time.sleep(espera)
            else:
                siguiente = time.monotonic()

    # Compatibilidad: el giro de la torreta era la única articulación auxiliar
    giro_objetivo = property(lambda self: self.objetivos["giro"])
    vel_giro = property(lambda self: self.velocidades["giro"])

    def _mover_auxiliares(self, dt):
        for nombre in AUXILIARES:
            self._mover_auxiliar(nombre, dt)

    def _mover_auxiliar(self, nombre, dt):
        """Va hacia su objetivo con velocidad y aceleración limitadas, sin chocar."""
        art = getattr(self.cfg, AUXILIARES[nombre])
        actual, vel = getattr(self.cfg, nombre), self.velocidades[nombre]
        error = self.objetivos[nombre] - actual
        if error == 0 and vel == 0:
            return
        # Velocidad que todavía permite frenar a tiempo, como en el firmware
        frenada = math.copysign(math.sqrt(2 * art.amax * abs(error)), error)
        deseada = max(-art.vmax, min(art.vmax, frenada))
        vel += max(-art.amax * dt, min(art.amax * dt, deseada - vel))
        nuevo = actual + vel * dt
        # Nunca cruza el objetivo: pasarse y volver sería un temblor en el servo
        if (self.objetivos[nombre] - nuevo) * error <= 0 or (abs(self.objetivos[nombre] - nuevo) < 0.02
                                                              and abs(vel) < art.amax * dt):
            nuevo, vel = self.objetivos[nombre], 0.0
        # Girar la torreta cambia lo que la caja pone bajo el brazo; mover la mano, dónde está
        movido = replace(self.cfg, **{nombre: nuevo})
        pose = self._pose_que_gira()
        hg = holgura(movido, *pose)
        if hg.mm < min(-TOLERANCIA_GIRO, holgura(self.cfg, *pose).mm):
            self.objetivos[nombre], self.velocidades[nombre] = actual, 0.0
            self.aviso = f"Detenido: {hg.donde}"
            return
        self.velocidades[nombre] = vel
        self.cfg = movido

    def _pose_que_gira(self):
        """La pose que hay que proteger: si el servo gira pero el brazo no sigue al dibujo, la del brazo real."""
        if self.salida_giro is not None and self.pose_real is not None and not (self.real and self.real["habilitado"]):
            real = self.pose_real()
            if real is not None:
                return real
        return self.pos

    def _parar_auxiliares(self):
        """Fija como objetivo de cada una el punto donde se detiene frenando desde su velocidad actual."""
        for nombre, lim in AUXILIARES.items():
            v = self.velocidades[nombre]
            self.objetivos[nombre] = getattr(self.cfg, nombre) + v * abs(v) / (2 * getattr(self.cfg, lim).amax)

    def _paso(self, dt):
        self._mover_auxiliares(dt)
        cfg = self.cfg
        if self.plan is not None:
            self._plan_i += 1
            ultimo = len(self.plan.hombro) - 1
            i = min(self._plan_i, ultimo)
            nueva = [self.plan.hombro[i], self.plan.codo[i]]
            self.vel = [(n - p) / dt for n, p in zip(nueva, self.pos)]
            self.pos = nueva
            if i >= ultimo:
                self.plan = None
                self.vel = [0.0, 0.0]
                self.aviso = ""
            return

        deseada, aviso_joy = [0.0, 0.0], ""
        if self.joy is not None and time.monotonic() - self.joy[1] < SIN_JOYSTICK:
            deseada, aviso_joy = self._vel_joystick(self.joy[0], dt)
        for k, art in enumerate((cfg.hombro, cfg.codo)):
            self.vel[k] += max(-art.amax * dt, min(art.amax * dt, deseada[k] - self.vel[k]))
        if self.vel == [0.0, 0.0]:
            if not aviso_joy and self.aviso.startswith("El codo"):
                self.aviso = ""
            return

        candidato = [p + v * dt for p, v in zip(self.pos, self.vel)]
        for k, art in enumerate((cfg.hombro, cfg.codo)):
            if not art.minimo <= candidato[k] <= art.maximo:
                candidato[k] = min(max(candidato[k], art.minimo), art.maximo)
                self.vel[k] = 0.0
        self.pos, aviso = self._proteger(candidato, dt)
        self.aviso = aviso or aviso_joy

    def _vel_joystick(self, ordenes, dt):
        cfg = self.cfg
        if ordenes["modo"] == "punta":
            x, y = puntos(cfg, *self.pos)["punta"]
            objetivo = inversa(cfg, x + ordenes["x"] * VEL_PUNTA * dt,
                               y + ordenes["y"] * VEL_PUNTA * dt, self.pos[1])
            if objetivo is None:
                return [0.0, 0.0], "La punta no alcanza más lejos"
            vel = [(o - p) / dt for o, p in zip(objetivo, self.pos)]
            # Misma escala para ambas: la punta conserva la dirección pedida
            escala = min([1.0] + [art.vmax / abs(v) for art, v in zip((cfg.hombro, cfg.codo), vel) if v])
            return [v * escala for v in vel], ""
        return [ordenes["hombro"] * cfg.hombro.vmax, ordenes["codo"] * cfg.codo.vmax], ""

    def _proteger(self, candidato, dt):
        """Evita que el siguiente paso toque algo: primero flexiona el codo y, si no basta, se detiene."""
        cfg = self.cfg
        piso = min(0.0, holgura(cfg, *self.pos).mm)
        hc = holgura(cfg, *candidato)
        if hc.mm >= piso:
            return candidato, ""
        # Solo se corrige con el codo si el que baja es el hombro; si el usuario
        # mueve el codo hacia la mesa, se detiene en lugar de llevarle la contraria
        if abs(candidato[0] - self.pos[0]) > 1e-9:
            paso = cfg.codo.vmax * dt
            objeto = "la base" if "base" in hc.donde else "la mesa"
            # Primero el hombro sigue y el codo se flexiona a la vez. Si no alcanza
            # (con el antebrazo casi vertical, flexionar apenas sube la punta), el
            # hombro espera este ciclo mientras el codo abre espacio
            for hombro in (candidato[0], self.pos[0]):
                for sentido in (self._sentido, -self._sentido):
                    codo = self.pos[1] + sentido * paso
                    if dentro_de_limites(cfg, hombro, codo) and holgura(cfg, hombro, codo).mm >= piso:
                        self._sentido = sentido
                        self.vel = [(hombro - self.pos[0]) / dt, (codo - self.pos[1]) / dt]
                        return [hombro, codo], f"El codo se flexiona para esquivar {objeto}"
        # Avanzar justo hasta el límite y quedarse ahí. Quedarse un paso antes hacía
        # que el siguiente paso, más corto, sí cupiera: el brazo avanzaba a tirones
        # (se mueve, se detiene, se mueve) y el aviso parpadeaba
        self.vel = [0.0, 0.0]
        return self._hasta_el_limite(candidato, piso), f"Detenido: {hc.donde}"

    def _hasta_el_limite(self, candidato, piso):
        """El punto más lejano del paso hacia `candidato` que todavía respeta la holgura."""
        bien, mal = 0.0, 1.0
        for _ in range(12):
            t = (bien + mal) / 2
            pose = [p + t * (c - p) for p, c in zip(self.pos, candidato)]
            if holgura(self.cfg, *pose).mm >= piso:
                bien = t
            else:
                mal = t
        return [p + bien * (c - p) for p, c in zip(self.pos, candidato)]

    # --- órdenes ---

    def vista_previa(self, destino):
        with self._lock:
            cfg, pos, vel = self.cfg, list(self.pos), list(self.vel)
        return _resumen(cfg, planificar(cfg, pos, vel, destino), destino)

    def mover(self, destino, duracion=None):
        with self._lock:
            plan = planificar(self.cfg, self.pos, self.vel, destino, duracion)
            resumen = _resumen(self.cfg, plan, destino)
            if plan.valido:
                self.plan, self._plan_i, self._plan_resumen = plan, 0, resumen
                self.joy = None
                self.aviso = plan.motivo
                self._parar_auxiliares()  # el plan se comprobó con la torreta y la mano así
            return resumen

    def ir_a_reposo(self):
        return self.mover((self.cfg.reposo_hombro, self.cfg.reposo_codo))

    def joystick(self, datos):
        modo = datos.get("modo")
        if modo == "punta":
            ordenes = {"modo": modo, "x": _unidad(datos.get("x")), "y": _unidad(datos.get("y"))}
        elif modo == "articulaciones":
            ordenes = {"modo": modo, "hombro": _unidad(datos.get("hombro")), "codo": _unidad(datos.get("codo"))}
        else:
            raise ValueError("modo de joystick desconocido")
        with self._lock:
            if self.plan is not None and any(v for k, v in ordenes.items() if k != "modo"):
                self.plan = None  # el usuario toma el control; la velocidad actual se frena suave
            self.joy = (ordenes, time.monotonic())

    def sincronizar(self, hombro, codo):
        """Coloca el simulador en una pose sin moverse hasta ella (la del brazo real)."""
        with self._lock:
            self.pos = [hombro, codo]
            self.vel = [0.0, 0.0]
            self.plan = None
            self.joy = None
            self.aviso = ""

    def detener(self):
        with self._lock:
            self.plan = None
            self.joy = None
            self._parar_auxiliares()

    def mover_auxiliar(self, nombre, valor):
        """Nuevo objetivo de una articulación auxiliar, dentro de sus límites. Devuelve el aplicado."""
        with self._lock:
            if nombre not in AUXILIARES:
                raise ValueError(f"articulación desconocida: {nombre}")
            if self.plan is not None:
                raise ValueError("Espera a que termine el movimiento")
            if nombre != "giro" and not self.cfg.garra_montada:
                raise ValueError("La garra no está montada (Medidas y límites)")
            art = getattr(self.cfg, AUXILIARES[nombre])
            self.objetivos[nombre] = min(max(valor, art.minimo), art.maximo)
            if self.aviso.startswith("Detenido"):
                self.aviso = ""
            return self.objetivos[nombre]

    def girar(self, angulo):
        """Nuevo objetivo de la torreta, dentro de sus límites. Devuelve el objetivo aplicado."""
        return self.mover_auxiliar("giro", angulo)

    def sincronizar_giro(self, giro):
        """Coloca la torreta en un giro sin moverse hasta él (el del servo real)."""
        with self._lock:
            self.cfg = replace(self.cfg, giro=giro)
            self.objetivos["giro"], self.velocidades["giro"] = giro, 0.0

    def actualizar_config(self, cfg):
        with self._lock:
            self.cfg = cfg
            self.version += 1
            self.plan = None
            self.vel = [0.0, 0.0]
            for nombre, lim in AUXILIARES.items():
                art = getattr(cfg, lim)
                self.objetivos[nombre] = min(max(self.objetivos[nombre], art.minimo), art.maximo)

    def fijar_reposo_aqui(self):
        with self._lock:
            datos = self.cfg.a_dict()
            datos["reposo_hombro"] = round(self.pos[0], 1)
            datos["reposo_codo"] = round(self.pos[1], 1)
        cfg = Config.desde_dict(datos)
        self.actualizar_config(cfg)
        return cfg

    # --- estado para la página ---

    def config_dict(self):
        with self._lock:
            return {**self.cfg.a_dict(), "version": self.version, "base_plano": list(base_en_plano(self.cfg))}

    def estado(self):
        with self._lock:
            return self._estado()

    def _estado(self):
        cfg = self.cfg
        hg = holgura(cfg, *self.pos)
        if self.plan is not None:
            modo = "plan"
        elif any(self.vel):
            modo = "moviendo"
        else:
            modo = "quieto"
        estado = {
            "hombro": round(self.pos[0], 2),
            "codo": round(self.pos[1], 2),
            "puntos": _redondear(puntos(cfg, *self.pos)),
            "holgura": round(hg.mm, 1),
            "donde": hg.donde,
            "modo": modo,
            "aviso": self.aviso,
            "version_config": self.version,
            "simulado": not (self.real and self.real["habilitado"]),
            "real": self.real,
            "giro": round(cfg.giro, 2),
            "giro_objetivo": round(self.objetivos["giro"], 2),
            "mano": {"montada": cfg.garra_montada, "radios": [round(r, 1) for r in radios_mano(cfg)],
                     **{k: round(getattr(cfg, k), 2) for k in ("muneca", "giro_muneca", "garra")},
                     "objetivos": {k: round(self.objetivos[k], 2) for k in ("muneca", "giro_muneca", "garra")}},
            "base_plano": [round(v, 1) for v in base_en_plano(cfg)],
            "giro_real": self.giro_real() if self.giro_real else None,
            "rutina": self.rutina() if self.rutina else None,
        }
        if self.real is not None and self.pose_real is not None:
            pose = self.pose_real()
            if pose is not None:
                estado["real"] = {**self.real, "hombro": round(pose[0], 1), "codo": round(pose[1], 1),
                                  "puntos": _redondear(puntos(cfg, *pose))}
        if self.plan is not None:
            estado["plan"] = {
                "traza": self._plan_resumen["traza"],
                "final": self._plan_resumen["final"],
                "progreso": round(self._plan_i / (len(self.plan.hombro) - 1), 3),
            }
        return estado

    def suscribir(self):
        cola = queue.Queue(maxsize=2)
        with self._lock:
            self._oyentes.add(cola)
            cola.put(self._estado())
        return cola

    def anular(self, cola):
        with self._lock:
            self._oyentes.discard(cola)

    def _publicar(self, estado):
        with self._lock:
            oyentes = list(self._oyentes)
        for cola in oyentes:
            # Si un cliente va lento, se descarta el estado viejo: solo importa el último
            try:
                cola.put_nowait(estado)
            except queue.Full:
                try:
                    cola.get_nowait()
                    cola.put_nowait(estado)
                except (queue.Empty, queue.Full):
                    pass


def _unidad(valor):
    v = float(valor or 0.0)
    if not math.isfinite(v):
        raise ValueError("valor de joystick inválido")
    return max(-1.0, min(1.0, v))


def _redondear(pts):
    return {k: [round(x, 1), round(y, 1)] for k, (x, y) in pts.items()}


def _resumen(cfg, plan, destino):
    """Lo que la página necesita para dibujar un plan (o explicar por qué no se puede)."""
    datos = {
        "valido": plan.valido,
        "motivo": plan.motivo,
        "duracion": round(plan.duracion, 2),
        "corregido": round(plan.corregido, 1),
        "solicitado": _redondear(puntos(cfg, *destino)),
    }
    if plan.valido:
        muestras = list(zip(plan.hombro, plan.codo))[::5] + [(plan.hombro[-1], plan.codo[-1])]
        datos["traza"] = [[round(v, 1) for v in puntos(cfg, h, c)["punta"]] for h, c in muestras]
        datos["final"] = _redondear(puntos(cfg, plan.hombro[-1], plan.codo[-1]))
        datos["destino"] = [round(plan.hombro[-1], 1), round(plan.codo[-1], 1)]
    return datos
