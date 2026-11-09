"""Enlace serie con el Nano (firmware BrazoNano).

En Linux y macOS usa termios, sin dependencias. En Windows hace falta pyserial
(`pip install pyserial`); si está instalado, también sirve para buscar el puerto.

Abrir el puerto puede reiniciar el Nano (DTR). Sin pose de inicio guardada, el
firmware arranca sin mandar señal y conectar no mueve el brazo; con pose de
inicio, va a ella como al encender. Si se desenchufa, se reintenta.
"""
import glob
import os
import threading
import time

try:
    import select
    import termios
except ImportError:  # Windows
    termios = None
try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None

SERVOS = ("hombro_izq", "hombro_der", "codo", "giro")
GIRO = SERVOS.index("giro")
NUM_INICIO = 3  # la pose de inicio del firmware: hombros y codo; el giro arranca sin señal


def buscar_puerto():
    """El primer puerto serie por USB: /dev/ttyUSB0 en Linux, COM3 o similar en Windows."""
    if serial is not None:
        usb = sorted(p.device for p in list_ports.comports() if p.vid is not None)
        if usb:
            return usb[0]
    puertos = sorted(glob.glob("/dev/ttyUSB*")) + sorted(glob.glob("/dev/ttyACM*"))
    return puertos[0] if puertos else None


class _PuertoPosix:
    """termios directo. Sin HUPCL: cerrar el puerto no reinicia el Nano."""

    def __init__(self, ruta):
        fd = os.open(ruta, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            a = termios.tcgetattr(fd)
            a[0] = a[1] = a[3] = 0
            a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
            a[4] = a[5] = termios.B115200
            a[6][termios.VMIN] = 0
            a[6][termios.VTIME] = 0
            termios.tcsetattr(fd, termios.TCSANOW, a)
            termios.tcflush(fd, termios.TCIOFLUSH)
        except OSError:
            os.close(fd)
            raise
        self.fd = fd

    def leer(self):
        """Lo que llegó en 0,2 s (b"" si nada); OSError si el puerto se cerró."""
        listo, _, _ = select.select([self.fd], [], [], 0.2)
        if not listo:
            return b""
        datos = os.read(self.fd, 512)
        if not datos:
            raise OSError("puerto cerrado")
        return datos

    def escribir(self, datos):
        os.write(self.fd, datos)

    def cerrar(self):
        os.close(self.fd)


class _PuertoSerial:
    """pyserial, para Windows. DTR apagado antes de abrir: en muchos adaptadores evita reiniciar el Nano."""

    def __init__(self, ruta):
        s = serial.Serial()
        s.port, s.baudrate, s.timeout = ruta, 115200, 0.2
        s.dtr = False
        try:
            s.open()
            s.reset_input_buffer()
        except serial.SerialException as e:
            raise OSError(str(e)) from None
        self.s = s

    def leer(self):
        try:
            return self.s.read(512)
        except serial.SerialException as e:
            raise OSError(str(e)) from None

    def escribir(self, datos):
        try:
            self.s.write(datos)
        except serial.SerialException as e:
            raise OSError(str(e)) from None

    def cerrar(self):
        self.s.close()


def leer_informe(linea):
    """'E 1 1472 0 1500 1 1472 0 1500' → [{'activo': True, 'us': 1472}, ...] o None si no es un informe.

    Un firmware anterior informa menos servos: no se acepta y el Nano figura como que no responde.
    """
    partes = linea.split()
    if len(partes) != 1 + 2 * len(SERVOS) or partes[0] != "E":
        return None
    try:
        valores = [int(v) for v in partes[1:]]
    except ValueError:
        return None
    return [{"activo": bool(valores[2 * i]), "us": valores[2 * i + 1]} for i in range(len(SERVOS))]


class Nano:
    def __init__(self, puerto=None):
        self.puerto_pedido = puerto  # None = el primero que aparezca
        self.puerto = None
        self._lock = threading.Lock()
        self._puerto = None
        self.error = ""  # por qué no se puede abrir el puerto, para la página
        self.firmware = ""
        self.inicio = None  # pose de inicio guardada en la EEPROM: [us0, us1, us2]
        self.reinicios = 0  # cuántas veces arrancó el firmware mientras estábamos conectados
        self._ultimo_informe = 0.0
        self.servos = [{"activo": False, "us": None} for _ in SERVOS]
        threading.Thread(target=self._bucle, daemon=True, name="nano").start()

    # --- órdenes ---

    def activar(self, servo, us):
        self._enviar(f"A {servo} {int(round(us))}")

    def objetivo(self, servo, us):
        self._enviar(f"S {servo} {int(round(us))}")

    def soltar(self, servo):
        self._enviar(f"D {servo}")

    def soltar_todos(self):
        self._enviar("X")

    def guardar_inicio(self, pulsos):
        self._enviar("G " + " ".join(str(int(round(us))) for us in pulsos))

    def borrar_inicio(self):
        self._enviar("B")

    def estado(self):
        with self._lock:
            return {
                "puerto": self.puerto,
                "conectado": self._puerto is not None,
                "error": self.error,
                "responde": time.monotonic() - self._ultimo_informe < 1.0,
                "firmware": self.firmware,
                "inicio": self.inicio,
                "reinicios": self.reinicios,
                "servos": [dict(s, nombre=n) for s, n in zip(self.servos, SERVOS)],
            }

    def _enviar(self, texto):
        with self._lock:
            if self._puerto is None:
                raise ConnectionError("el Nano no está conectado")
            try:
                self._puerto.escribir((texto + "\n").encode())
            except OSError as e:
                # Desenchufado: quien envía (p. ej. el puente) lo trata como desconexión
                raise ConnectionError(f"no se pudo escribir al Nano: {e}") from None

    # --- lectura ---

    def _bucle(self):
        pendiente = b""
        consultar = None  # cuándo preguntar la pose de inicio si el Nano no la informó solo
        while True:
            if self._puerto is None:
                if not self._abrir():
                    time.sleep(2)
                    continue
                pendiente = b""
                # Si abrir el puerto lo reinició, la informa al arrancar; si no, hay que pedirla
                consultar = time.monotonic() + 2.5
            if consultar is not None and time.monotonic() > consultar:
                consultar = None
                if self.inicio is None:
                    try:
                        self._enviar("?")
                    except (ConnectionError, OSError):
                        pass
            try:
                datos = self._puerto.leer()
            except OSError:
                self._cerrar()
                continue
            if not datos:
                continue
            pendiente += datos
            *lineas, pendiente = pendiente.split(b"\n")
            for linea in lineas:
                self._procesar(linea.decode(errors="replace").strip())

    def _procesar(self, linea):
        informe = leer_informe(linea)
        with self._lock:
            if informe is not None:
                self.servos = informe
                self._ultimo_informe = time.monotonic()
            elif "LISTO" in linea:  # tras el reinicio puede llegar basura del cargador antes
                self.firmware = linea.split("LISTO", 1)[1].strip()
                self.reinicios += 1
            elif linea.startswith("INICIO"):
                partes = linea.split()[1:]
                self.inicio = [int(v) for v in partes] if len(partes) == NUM_INICIO else None
                self.servos = [{"activo": False, "us": None} for _ in SERVOS]

    def _abrir(self):
        if termios is None and serial is None:
            self.error = "En Windows falta pyserial: pip install pyserial"
            return False
        puerto = self.puerto_pedido or buscar_puerto()
        if not puerto:
            return False
        try:
            enlace = _PuertoPosix(puerto) if termios is not None else _PuertoSerial(puerto)
        except OSError as e:
            self.error = f"No se pudo abrir {puerto}: {e}"
            return False
        with self._lock:
            self._puerto, self.puerto = enlace, puerto
            self.error = ""
            self.firmware = ""
        return True

    def _cerrar(self):
        with self._lock:
            if self._puerto is not None:
                try:
                    self._puerto.cerrar()
                except OSError:
                    pass
            self._puerto = None
            self.servos = [{"activo": False, "us": None} for _ in SERVOS]
