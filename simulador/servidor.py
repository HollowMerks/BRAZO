#!/usr/bin/env python3
"""Servidor del simulador del brazo robótico.

Etapa A: simulación. Etapa B1 (con --nano): calibración del brazo real servo
por servo. Sin --nano no se toca el puerto serie.

Sirve la página (laptop y celular) y una API JSON pequeña. Escucha solo en
localhost y en la IP de Tailscale: el brazo no debe poder manejarse desde
cualquier equipo de una WiFi compartida (por ejemplo, la de la universidad).

Uso: python3 servidor.py [--nano [puerto]] [--abrir] [--puerto 8765] [--escuchar 127.0.0.1,100.x.y.z]
     El puerto del Nano se busca solo (/dev/ttyUSB0 en Linux, COM3 o similar en Windows).
"""
import argparse
import ipaddress
import json
import math
import queue
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from motor.calibracion import Calibracion
from motor.config import Config, cargar, guardar
from motor.control import AUXILIARES, Controlador
from motor.fisico import Fisico
from motor.giro import PuenteGiro
from motor.nano import SERVOS, Nano
from motor.puente import Puente
from motor.rutinas import Rutinas

RAIZ = Path(__file__).resolve().parent
WEB = RAIZ / "web"
RUTA_CONFIG = RAIZ / "datos" / "config.json"
RUTA_CALIBRACION = RAIZ / "datos" / "calibracion.json"
CARPETA_RUTINAS = RAIZ / "datos" / "rutinas"
# Órdenes que moverían el brazo por su cuenta: no se aceptan mientras corre una rutina
MANUALES = {"/api/mover", "/api/reposo", "/api/giro", "/api/mano", "/api/hombros", "/api/codo",
            "/api/calibracion/sostener", "/api/inicio/ir"}
ESTATICOS = {"/": "index.html", "/index.html": "index.html", "/estilo.css": "estilo.css", "/app.js": "app.js",
             "/vista3d.js": "vista3d.js"}
# Librerías (three.js) y mallas del modelo 3D: archivos fijos, sin subcarpetas
CARPETAS = {"vendor", "modelo"}
TIPOS = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".js": "text/javascript; charset=utf-8", ".json": "application/json; charset=utf-8",
         ".bin": "application/octet-stream"}
PERMITIDAS = [ipaddress.ip_network(r) for r in ("127.0.0.0/8", "::1/128", "100.64.0.0/10")]
MAX_CUERPO = 16 * 1024

control = None
calibracion = None
fisico = None  # solo con --nano
puente = None
puente_giro = None
rutinas = None


def _pose(datos):
    pose = (float(datos["hombro"]), float(datos["codo"]))
    if not all(math.isfinite(v) for v in pose):
        raise ValueError("ángulos inválidos")
    return pose


def _duracion(datos):
    if datos.get("duracion") is None:
        return None
    d = float(datos["duracion"])
    if not 0 < d <= 60:
        raise ValueError("la duración debe estar entre 0 y 60 s")
    return d


class Manejador(BaseHTTPRequestHandler):
    server_version = "BrazoSim/1"

    def log_message(self, formato, *args):
        pass  # la página consulta seguido; no llenar la terminal

    def _permitido(self):
        try:
            ip = ipaddress.ip_address(self.client_address[0])
        except ValueError:
            return False
        return any(ip in red for red in PERMITIDAS)

    def _json(self, datos, codigo=200):
        cuerpo = json.dumps(datos, ensure_ascii=False).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(cuerpo)

    def _leer(self):
        largo = int(self.headers.get("Content-Length") or 0)
        if largo > MAX_CUERPO:
            raise ValueError("petición demasiado grande")
        return json.loads(self.rfile.read(largo) or b"{}")

    def do_GET(self):
        if not self._permitido():
            return self.send_error(403)
        ruta = self.path.split("?")[0]
        partes = ruta.strip("/").split("/")
        if len(partes) == 2 and partes[0] in CARPETAS:
            self._archivo_fijo(WEB / partes[0], partes[1])
        elif ruta in ESTATICOS:
            archivo = WEB / ESTATICOS[ruta]
            cuerpo = archivo.read_bytes()
            if archivo.suffix == ".html":
                # Config y estado incrustados: la página dibuja el brazo sin esperar a la API
                inicial = json.dumps({"config": control.config_dict(), "estado": control.estado()}, ensure_ascii=False)
                cuerpo = cuerpo.replace(b"/*INICIAL*/null", inicial.replace("</", "<\\/").encode())
            self.send_response(200)
            self.send_header("Content-Type", TIPOS[archivo.suffix])
            self.send_header("Content-Length", str(len(cuerpo)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(cuerpo)
        elif ruta == "/api/config":
            self._json(control.config_dict())
        elif ruta == "/api/estado":
            self._json(control.estado())
        elif ruta == "/api/eventos":
            self._eventos()
        elif ruta == "/api/fisico":
            self._json(fisico.estado() if fisico else {"sin_nano": True})
        elif ruta == "/api/calibracion":
            self._json(calibracion.resumen())
        elif ruta == "/api/rutinas":
            self._json({"rutinas": rutinas.lista(), "estado": rutinas.estado()})
        else:
            self.send_error(404)

    def _archivo_fijo(self, carpeta, nombre):
        """Un archivo de vendor/ o modelo/; el navegador lo guarda y solo pregunta si cambió."""
        archivo = carpeta / nombre
        if (nombre.startswith(".") or archivo.suffix not in TIPOS or archivo.parent != carpeta
                or not archivo.is_file()):
            return self.send_error(404)
        info = archivo.stat()
        etiqueta = f'"{info.st_mtime_ns:x}-{info.st_size:x}"'
        if self.headers.get("If-None-Match") == etiqueta:
            self.send_response(304)
            self.send_header("ETag", etiqueta)
            self.end_headers()
            return
        cuerpo = archivo.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", TIPOS[archivo.suffix])
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("ETag", etiqueta)
        self.end_headers()
        self.wfile.write(cuerpo)

    def _eventos(self):
        """Estado del brazo en vivo (Server-Sent Events, 25 por segundo)."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        cola = control.suscribir()
        try:
            while True:
                try:
                    estado = cola.get(timeout=15)
                    self.wfile.write(b"data: " + json.dumps(estado, ensure_ascii=False).encode() + b"\n\n")
                except queue.Empty:
                    self.wfile.write(b": sigue\n\n")
                self.wfile.flush()
        except OSError:
            pass
        finally:
            control.anular(cola)

    def do_POST(self):
        if not self._permitido():
            return self.send_error(403)
        ruta = self.path.split("?")[0]
        try:
            datos = self._leer()
            if rutinas.estado()["activa"] and ruta in MANUALES:
                return self._json({"error": "Hay una rutina en marcha: detenla primero"}, 409)
            if ruta == "/api/vista_previa":
                self._json(control.vista_previa(_pose(datos)))
            elif ruta == "/api/mover":
                self._json(control.mover(_pose(datos), _duracion(datos)))
            elif ruta == "/api/joystick":
                # Tocar un joystick durante una rutina la corta: manda el usuario
                if rutinas.estado()["activa"] and any(v for k, v in datos.items() if k != "modo"):
                    rutinas.detener()
                control.joystick(datos)
                self._json({"ok": True})
            elif ruta == "/api/detener":
                rutinas.detener()
                self._json({"ok": True})
            elif ruta == "/api/reposo":
                self._json(control.ir_a_reposo())
            elif ruta.startswith("/api/giro"):
                self._giro(ruta, datos)
            elif ruta.startswith("/api/rutina/"):
                self._rutina(ruta, datos)
            elif ruta == "/api/mano":
                # Cualquiera de muneca, giro_muneca y garra; devuelve los objetivos aplicados
                objetivos = {}
                for nombre in ("muneca", "giro_muneca", "garra"):
                    if datos.get(nombre) is not None:
                        valor = float(datos[nombre])
                        if not math.isfinite(valor):
                            raise ValueError(f"{nombre} inválido")
                        objetivos[nombre] = control.mover_auxiliar(nombre, valor)
                self._json({"objetivos": objetivos})
            elif ruta == "/api/reposo_aqui":
                cfg = control.fijar_reposo_aqui()
                guardar(cfg, RUTA_CONFIG)
                self._json(control.config_dict())
            elif ruta.startswith(("/api/calibracion/", "/api/inicio/", "/api/real/")) or ruta in ("/api/hombros", "/api/codo", "/api/soltar"):
                self._calibracion(ruta, datos)
            else:
                self.send_error(404)
        except ConnectionError as e:
            self._json({"error": f"Nano: {e}"}, 409)
        except (ValueError, TypeError, KeyError, IndexError) as e:
            self._json({"error": str(e)}, 400)

    def _rutina(self, ruta, datos):
        accion = ruta.rsplit("/", 1)[1]
        if accion == "leer":
            return self._json({"pasos": rutinas.leer(datos["nombre"])})
        if accion == "guardar":
            return self._json({"pasos": rutinas.guardar(datos["nombre"], datos["pasos"]), "rutinas": rutinas.lista()})
        if accion == "borrar":
            rutinas.borrar(datos["nombre"])
            return self._json({"rutinas": rutinas.lista()})
        if accion == "comprobar":
            return self._json(rutinas.comprobar(datos["pasos"]))
        if accion == "ejecutar":
            pasos = datos.get("pasos") or rutinas.leer(datos["nombre"])
            return self._json(rutinas.ejecutar(datos.get("nombre", ""), pasos))
        if accion == "detener":
            rutinas.detener()
            return self._json(rutinas.estado())
        self.send_error(404)

    def _cambiar_calibracion(self, ruta, datos):
        """Cambia la calibración sin que el brazo real salte.

        Con el puente habilitado, cada pose del dibujo se convierte a pulsos con la
        calibración vigente: si cambia de golpe, el mismo ángulo pide otro pulso y el
        servo saltaría. Por eso se deshabilita, se cambia y se vuelve a habilitar, que
        coloca el dibujo donde está el brazo según la calibración nueva.
        """
        seguia = puente is not None and puente.habilitado
        if seguia:
            puente.deshabilitar()
        try:
            if ruta == "/api/calibracion/punto":
                angulo = float(datos["angulo"])
                if datos["servo"] not in SERVOS or not math.isfinite(angulo):
                    raise ValueError("servo o ángulo inválido")
                calibracion.agregar(datos["servo"], float(datos["us"]), angulo)
            elif ruta == "/api/calibracion/borrar":
                calibracion.borrar(datos["servo"], int(datos["indice"]))
            else:
                if datos["servo"] not in SERVOS or datos["extremo"] not in ("min", "max"):
                    raise ValueError("servo o extremo inválido")
                us = datos.get("us")
                calibracion.fijar_limite(datos["servo"], 0 if datos["extremo"] == "min" else 1,
                                         None if us is None else float(us))
        finally:
            if seguia:
                try:
                    cfg, cambios = puente.habilitar()
                    if cambios:
                        guardar(cfg, RUTA_CONFIG)
                except (ValueError, ConnectionError) as e:
                    puente.deshabilitar(f"Calibración cambiada; no se pudo volver a habilitar: {e}")
        return calibracion.resumen()

    def _giro(self, ruta, datos):
        if ruta == "/api/giro":
            angulo = float(datos["angulo"])
            if not math.isfinite(angulo):
                raise ValueError("ángulo inválido")
            return self._json({"objetivo": control.girar(angulo)})
        if puente_giro is None:
            return self._json({"error": "Sin Nano: inicia el simulador con «python3 servidor.py --nano»"}, 409)
        if ruta == "/api/giro/habilitar":
            return self._json({"activado": puente_giro.habilitar()})
        if ruta == "/api/giro/deshabilitar":
            puente_giro.deshabilitar()
        elif ruta == "/api/giro/soltar":
            puente_giro.soltar()
        else:
            return self.send_error(404)
        self._json({"ok": True})

    def _calibracion(self, ruta, datos):
        if ruta in ("/api/calibracion/punto", "/api/calibracion/borrar", "/api/calibracion/limite"):
            return self._json(self._cambiar_calibracion(ruta, datos))
        if fisico is None:
            return self._json({"error": "Sin Nano: inicia el simulador con «python3 servidor.py --nano»"}, 409)
        if ruta == "/api/real/habilitar":
            cfg, cambios = puente.habilitar()
            if cambios:
                guardar(cfg, RUTA_CONFIG)
            return self._json({"ok": True, "cambios": cambios})
        if ruta == "/api/real/deshabilitar":
            puente.deshabilitar()
            return self._json({"ok": True})
        if ruta == "/api/soltar":
            puente.deshabilitar("Servos soltados: brazo real deshabilitado")
            puente_giro.deshabilitar()
            fisico.soltar()
            return self._json(fisico.estado())
        if puente.habilitado:
            return self._json({"error": "El brazo real sigue al simulador: deshabilítalo antes de moverlo desde aquí"}, 409)
        if ruta == "/api/hombros":
            fisico.mover_hombros(datos["us"])
        elif ruta == "/api/codo":
            fisico.mover_codo(datos["us"])
        elif ruta == "/api/calibracion/sostener":
            fisico.sostener_hombros(float(datos.get("angulo", 90)))
        elif ruta == "/api/inicio/guardar":
            fisico.guardar_inicio(datos.get("hombro_izq"), datos.get("codo"))
        elif ruta == "/api/inicio/ir":
            fisico.ir_a_inicio()
        elif ruta == "/api/inicio/borrar":
            fisico.nano.borrar_inicio()
        else:
            return self.send_error(404)
        self._json(fisico.estado())

    def do_PUT(self):
        if not self._permitido():
            return self.send_error(403)
        if self.path.split("?")[0] != "/api/config":
            return self.send_error(404)
        try:
            datos = self._leer()
            # Las lleva el control, no el formulario
            for nombre in AUXILIARES:
                datos[nombre] = getattr(control.cfg, nombre)
            cfg = Config.desde_dict(datos)
        except (ValueError, TypeError) as e:
            return self._json({"errores": [str(e)]}, 400)
        errores = cfg.errores()
        if errores:
            return self._json({"errores": errores}, 400)
        control.actualizar_config(cfg)
        guardar(cfg, RUTA_CONFIG)
        self._json(control.config_dict())


def _ip_tailscale():
    try:
        r = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        return None
    partes = r.stdout.split()
    return partes[0] if r.returncode == 0 and partes else None


def main():
    global control, calibracion, fisico, puente, puente_giro, rutinas
    p = argparse.ArgumentParser(description="Simulador del brazo (hombros + codo)")
    p.add_argument("--nano", nargs="?", const="auto",
                   help="conectar con el Nano (puerto o 'auto'); sin esto, solo simulación")
    p.add_argument("--abrir", action="store_true", help="abrir el simulador en el navegador")
    p.add_argument("--puerto", type=int, default=8765)
    p.add_argument("--escuchar", help="direcciones separadas por comas (por defecto: localhost y Tailscale)")
    args = p.parse_args()

    control = Controlador(cargar(RUTA_CONFIG))
    control.iniciar()
    rutinas = Rutinas(control, CARPETA_RUTINAS)
    calibracion = Calibracion(RUTA_CALIBRACION)
    if args.nano:
        # Abrir el puerto reinicia el Nano; el firmware arranca sin mover nada
        fisico = Fisico(Nano(None if args.nano == "auto" else args.nano), calibracion)
        puente = Puente(fisico, control)
        puente_giro = PuenteGiro(fisico.nano, control)
        print("Brazo real: buscando el Nano", "" if args.nano == "auto" else f"en {args.nano}", flush=True)

    if args.escuchar:
        direcciones = args.escuchar.split(",")
    else:
        direcciones = ["127.0.0.1"]
        ip = _ip_tailscale()
        if ip:
            direcciones.append(ip)
        else:
            print("Tailscale no responde: solo se podrá abrir desde esta laptop", file=sys.stderr)

    activos = 0
    for direccion in direcciones:
        try:
            servidor = ThreadingHTTPServer((direccion, args.puerto), Manejador)
        except OSError as e:
            print(f"No pude escuchar en {direccion}:{args.puerto}: {e}", file=sys.stderr)
            continue
        servidor.daemon_threads = True
        threading.Thread(target=servidor.serve_forever, daemon=True).start()
        print(f"Simulador en http://{direccion}:{args.puerto}", flush=True)
        activos += 1
    if not activos:
        sys.exit(1)
    if args.abrir:
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{args.puerto}")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
