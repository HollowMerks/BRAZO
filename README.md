# Brazo robótico: simulador y control

Simulador web y control por USB de un brazo robótico impreso en 3D: el diseño «Robotic
Arm with Servo & Arduino» de Emre Kalem (MakerWorld). Tiene un Arduino Nano, 4 MG995
(dos hombros espejados, codo y giro de la base) y 3 MG90S en la garra.

- **Simulador en el navegador** (laptop o celular), con vista 3D y lateral.
- **Protección contra choques** con la mesa y la caja.
- **Joysticks, poses y rutinas** que se repiten.
- **Brazo real:** sigue al simulador cuando se lo habilita.

## Para empezar (traspaso del 08/11/2026)

### Qué hace falta

- **Python 3.9 o más nuevo.** En Linux y macOS no necesita paquetes. **En Windows:**
  `pip install pyserial`; sin él, el simulador anda pero no encuentra el Nano.
- **Arduino IDE**, para grabar el firmware del Nano.
- **Navegador moderno**, con WebGL para la vista 3D.

### El modelo 3D (no viene en el repositorio)

La licencia del diseño es la «Standard Digital File License» de MakerWorld, que no
permite redistribuir los archivos. Por eso no se incluyen ni el 3MF ni las mallas que
salen de él. Para tenerlo:

1. Descargar el 3MF de «Robotic Arm with Servo & Arduino» (Emre Kalem) en MakerWorld.
2. Guardarlo como `modelo/fuente/brazo.3mf`.
3. Generar las mallas:
   ```
   python3 simulador/herramientas/exportar_modelo.py modelo/fuente/brazo.3mf
   ```

Sin el modelo todo funciona igual, solo que la página usa la vista lateral.

### Arrancar el simulador

```
cd simulador
python3 servidor.py --abrir            # solo simulación
python3 servidor.py --nano --abrir     # con el Nano enchufado por USB
```

- En Windows, usar `py` en vez de `python3`. El puerto del Nano se busca solo
  (`/dev/ttyUSB0`, `COM3`…); si no lo encuentra, indicarlo: `--nano COM5`.
- La página queda en http://127.0.0.1:8765. Por seguridad solo escucha en la propia
  computadora y en la red de Tailscale, si está instalado. Desde el celular, entrar por
  la IP de Tailscale de la computadora.
- Pruebas: `cd simulador && python3 -m unittest discover -s pruebas`.

### Grabar el firmware

1. Cerrar el simulador: tiene ocupado el puerto.
2. En el Arduino IDE, abrir `firmware/BrazoNano/BrazoNano.ino`.
3. Placa «Arduino Nano», procesador «ATmega328P». Si la subida falla con `not in sync`,
   probar «ATmega328P (Old Bootloader)».
4. Subir.

### Conexiones y alimentación

| Señal | Servo |
|---|---|
| A0 | Codo |
| A1 | Hombro izquierdo |
| A2 | Hombro derecho (espejado: siempre al revés que el izquierdo) |
| D9 | Giro de la base |

- **Alimentación de los servos:** fuente externa, nunca del 5 V del Nano.
- **GND común:** el negativo de esa fuente, unido a un GND del Nano. Sin GND común los
  servos tiemblan, se mueven solos o no obedecen.
- **Voltaje:** 6 V. Los MG995 aguantan hasta unos 7,2 V y los MG90S de la garra hasta unos
  6 V. Medirlo sin servos conectados antes de enchufarlos.
- **Antes de cambiar cables,** apagar la fuente o pulsar «Soltar todos».
- **Los dos hombros** mueven el mismo eje: se mueven siempre juntos y espejados. Uno solo
  fuerza contra el otro, que sin señal queda trabado por sus engranajes.

### Estado del brazo en el traspaso (08/11)

Lo que funciona: simulador completo (3D, protección, joysticks, giro, garra, rutinas),
firmware de 4 servos y puente con el brazo real.

**Pendiente o sin resolver:**
1. **Hombro derecho:** en la última sesión (06/11) no respondía, aunque los pulsos salían
   bien del Nano. El izquierdo quedó **desacoplado** (sin su brazo de servo). Revisar
   cable de A2, alimentación y el servo.
2. **Regulador:** su salida variaba entre 6 y 8 V. Revisarlo o cambiarlo antes de usar el
   brazo; con la garra conectada es crítico.
3. **Pose de inicio:** está **borrada** en el Nano, que arranca sin mandar señal. Para
   activar los servos sin salto, poner el brazo a mano en la pose de inicio (hombros
   verticales, codo encogido) y activar desde el panel de calibración.
4. **Calibración incompleta** (`simulador/datos/calibracion.json`):
   - Hombros: 1891 µs = vertical (medido el 31/10, puede haber cambiado al desacoplar el
     izquierdo); el punto de 45° es estimado.
   - Codo: 2000 µs = colgando (−180°) es medido; 700 µs = −58,1° es estimado.
   - Topes de pulso sin marcar. Giro sin calibrar.
5. **La garra** solo existe en el simulador: falta agregar sus 3 MG90S al firmware
   (propuesta: D10, D11 y D12). Si no está montada, desactivar «Garra montada» en
   «Medidas y límites», para que no frene de más.
6. **La pieza gris** se acortó cortándola por la mitad: unos 50 mm menos, estimado sobre
   fotos. Medir de eje a eje con regla y corregir «Pieza gris: eje del hombro → doblez».

**Primeros pasos sugeridos:**
1. Arrancar solo el simulador y probar la página.
2. Revisar regulador, GND y cables.
3. Grabar el firmware si hace falta y arrancar con `--nano`.
4. Revisar el hombro derecho; volver a acoplar el izquierdo alineado (ver «Calibrar» más
   abajo).
5. Calibrar al ojo: mover con los joysticks hasta poses fáciles de reconocer (tramo gris
   vertical y a 45°, antebrazo horizontal y colgando) y registrar el pulso con ese ángulo.
6. Marcar los topes y guardar una pose de inicio.

### Créditos y licencias

- **Diseño del brazo:** Emre Kalem (MakerWorld), «Standard Digital File License». No se
  incluye.
- **three.js r170** (`simulador/web/vendor`): licencia MIT.

Lo que sigue es el detalle técnico y la historia del proyecto.

## Etapas

| Etapa | Contenido | Estado |
|---|---|---|
| A | Simulador: geometría, choques con mesa y caja, trayectorias coordinadas, joysticks; vista 3D con el modelo impreso (30/10) | **hecha** (sin hardware) |
| B1 | Firmware `BrazoNano` + panel de calibración + pose de inicio al encender | **hecha** (calibración incompleta, ver arriba) |
| B2 | Mover el brazo real desde el simulador (puente `motor/puente.py`, botón «Brazo real · Habilitar») | **hecha**, funciona desde el 28/10 |
| C | Grabar, editar y reproducir secuencias (simulador → brazo) | **hecha** en el simulador (06/11): panel «Rutinas» |
| D | Precisión: voltaje/corriente, detección de peleas entre hombros, funcionar sin laptop | pendiente |

## Calibrar el brazo real (etapa B1)

1. `python3 servidor.py --nano` con el Nano enchufado (sin pose de inicio, el firmware arranca sin mover nada).
2. Panel «Calibración (brazo real)» → «Hombros (los dos)»: se mueven SIEMPRE juntos,
   espejados alrededor de 1472 µs (donde se alinearon). Un hombro solo no sirve: sin
   señal el otro queda trabado por sus engranajes y se oye forzar. Medir el tramo recto
   gris con el inclinómetro del celular y «Registrar punto» en tres ángulos (algo
   adelante, vertical, algo atrás). El derecho se deduce como espejo del izquierdo.
3. Codo: hombros en vertical y medir el antebrazo en tres puntos.
4. Si al sostener en posiciones extremas los hombros zumban (se pelean), el espejo no
   basta: registrar puntos propios del derecho (la API lo admite).
5. Límites: «Fijar mínimo/máximo aquí» guarda el pulso actual como tope (los de los
   hombros se guardan sobre el izquierdo). Marcado el 28/10: máximo de los hombros =
   izquierdo 2070 / derecho 874 µs, tramo gris casi vertical.
   Codo: bajar los µs levanta el antebrazo; su tope hacia arriba es 700 µs.
6. Los puntos y límites quedan en `simulador/datos/calibracion.json`; las poses marcadas
   a mano (por ahora «recoger», en pulsos) en `simulador/datos/poses.json`.

Firmware: `firmware/BrazoNano` (v6) (protocolo en la cabecera del .ino; límites duros
700–2300 µs, 420 µs/s ≈ 39°/s desde el 28/10). Mientras el servidor usa el puerto no se puede grabar el Nano:
detener el servidor, grabar y volver a iniciarlo.

**Pose de inicio** (EEPROM del Nano): al encender activa los hombros juntos y luego el
codo en esa pose; sin pose guardada arranca sin señal. Guardada el 28/10: hombros
2070/874 (vertical) y codo 2000 (encogido), compacta y con el peso sobre la base, buena
para transportarlo. Antes de apagar: «Ir a inicio» (sube los hombros y después pliega el
codo), así al encender no salta.

**31/10: pose de inicio borrada.** Los dos hombros se calentaron peleando entre sí al
sostener 2070/874, tras un rato con cables cruzados. El Nano arranca sin señal hasta
realinearlos y volver a guardar un inicio. El Nano no mide corriente: que los pulsos
lleguen bien no descarta una pelea; se detecta por calor o zumbido.

**Cómo realinear los hombros** (así se hizo el 31/10):
1. Quitar el brazo de servo de un hombro, el izquierdo, para que no puedan pelear.
2. Con los dos recibiendo señal, llevarlos despacio desde el panel de calibración a una
   pose segura: abrir primero el codo y después llevar los hombros a 1750/1194 µs, unos
   60°, con el antebrazo lejos de la mesa. No usar un sketch que los mande de golpe al
   centro (1472 µs): con el brazo recortado, el antebrazo choca con la mesa.
3. Encajar el brazo del servo suelto en el diente que mejor calce, sin mover el brazo
   gris, y atornillarlo.
4. Comprobar activándolos por turnos: solo uno, solo el otro, los dos (órdenes `D` y `S`
   del firmware). Si el brazo no se desplaza al cambiar y no zumban, están alineados.

**Calibración actual** (28/10): hombros 1270 µs = 15° y 2070 µs = 90° (0,094 °/µs,
coherente con el MG995); derecho = espejo. Límites: hombros 1270–2070 (el mínimo vale
con el codo levantado), codo 700 (levantado) – 2000 (encogido). Pose «recoger» en
`datos/poses.json`.
**30/10: límites liberados para recalibrar con el modelo 3D:**
- Pulsos sin límites propios; quedan los del firmware, 700–2300 µs.
- Simulador con hombro de 0 a 180° y codo de −180 a 0°.
- Se conservan los puntos de calibración. Los límites anteriores quedaron en
  `datos/calibracion-antes-de-liberar.json`.

## Brazo real siguiendo al simulador (etapa B2)

«Brazo real · Habilitar» (arriba de los joysticks). Al habilitar no se mueve nada: el
simulador se coloca donde está el brazo real (deducido de los pulsos que informa el
Nano) y desde ahí cada pose del bucle de control (límites + protección de la mesa) se
convierte a pulsos y se envía 25 veces por segundo. Al habilitar, la config del
simulador se recorta a lo calibrado: límites dentro de los pulsos marcados, velocidad
≤ 400 µs/s (el firmware limita a 420) y reposo = pose de inicio del Nano. Mientras está
habilitado, los botones de calibración no mueven nada; «Soltar todos» lo deshabilita.
Si el Nano se reinicia o se desconecta, se deshabilita solo.

## Modelo 3D (30/10)

Vista «3D» (por defecto) o «Lateral» arriba del dibujo. Se arrastra para girar la
cámara, con la rueda o dos dedos se acerca. Solo dibuja: la pose, los límites y los
choques siguen saliendo del servidor.

- Fuente: `modelo/fuente/brazo.3mf`, el diseño «Robotic Arm with Servo & Arduino» de
  Emre Kalem (MakerWorld) que imprimió el usuario. Es de un tercero: sirve para uso
  interno; **revisar su licencia antes de publicar** el simulador con las mallas.
- `simulador/herramientas/exportar_modelo.py` pasa la caja (Alt_Kasa), la torreta
  (Alt_Govde), el brazo gris (Alt_Kol) y el antebrazo (On_Kol) a `web/modelo/*.bin`, cada
  una en el marco de su eslabón. El 3MF trae las piezas sueltas en placas de impresión:
  el armado sale de los agujeros medidos en cada pieza (ver la cabecera del script).
- three.js r170 está copiado en `web/vendor/` para que funcione sin internet.
- Medidas que salen del modelo: eje del hombro → eje del codo 47,5 mm adelante y
  194,27 mm arriba con el tramo recto vertical (200 mm de eje a eje). Codo → eje de la
  muñeca 140 mm. Caja de 210 × 120 × 70 mm con el eje de giro en el centro de su extremo
  redondo. Servo del hombro con su eje 40 mm sobre el plato de la torreta.
- Comprobado con la foto del usuario del 30/10 (brazo en la pose de inicio):
  - La torreta va apoyada directo sobre la caja: eje del hombro a 110 mm de la mesa.
  - El eje del hombro queda ~10 mm detrás del eje de giro (`hombro_atras_giro` = 9,75).
    La ventana del servo está a 19,75 mm, y el eje del MG995 a ~10 mm de su centro, del
    lado del cable. Estimado sobre la foto, no medido con regla.
  - `giro` = 0 es como está armado: el brazo mira hacia el extremo redondo de la caja y lo
    largo de la caja queda detrás. Positivo = antihorario visto desde arriba.
- **La pieza gris real está cortada** por la mitad del tramo recto. La vista 3D la
  recorta a 86 mm del eje del hombro, según `brazo_recto` («Pieza gris: eje del hombro
  → doblez»): lo de arriba baja y la franja cortada desaparece; las amarillas no se
  tocan.
  - En el modelo el tramo recto mide 172,12 mm. El 30/10 quedó en 122,12 (50 mm menos,
    unos 152 mm de eje a eje), **estimado en dos fotos del usuario** (pose de inicio y
    plegado), que concuerdan con ±10 mm.
  - Falta medirlo con regla: tramo recto = √(eje_a_eje² − 47,5²) − 22,15.
- Lo que la caja pone bajo el brazo depende del giro (`cinematica.base_en_plano`). Se
  toma una franja de 56 mm (la horquilla del antebrazo) alrededor del plano del brazo, y
  la parte de la caja que cae dentro es el rectángulo con el que se comprueban los choques.

## Giro de la torreta (31/10)

El giro es el 4.º servo del firmware (`BrazoNano 6`) y una articulación del simulador.
Pines: hombro izquierdo A1, hombro derecho A2, codo A0, **giro D9**. Se usa con
`python3 servidor.py --nano`.

- Al encender, el Nano activa hombros y codo en la pose de inicio. El giro arranca **sin
  señal**: no forma parte de la pose de inicio.
- En la página: «Servo de giro · Habilitar» y el deslizador «Giro». El deslizador siempre
  mueve el dibujo; el servo lo sigue solo si está habilitado. «Detener» también frena el
  giro. No se puede girar durante un plan de «Ir a una pose».
- Al habilitar, si el servo está sostenido, el dibujo se coloca donde está. Si está suelto,
  el firmware lo activa en el giro del dibujo con pulsos sueltos durante unos 3 s, sin
  saltar a toda velocidad: es el único momento en que habilitar mueve el servo. Esos 3 s
  el Nano no atiende órdenes; los demás servos sostienen su último pulso.
- `motor/giro.py` traduce grados a pulsos con `giro_centro_us` y `giro_us_por_grado`
  (nominal, **sin calibrar**: 11,11 µs/°; con signo negativo invierte el sentido).
- Límites ±54°, que eligió el usuario: 900–2100 µs, también como tope en el firmware. 10°/s
  y 20°/s² en el simulador, por debajo de los 120 µs/s del firmware, para que el servo no
  se quede atrás; en la prueba del 31/10 lo siguió con ~0,4 s de atraso.
- Si girar metiera la caja bajo el brazo, la torreta se detiene (`Controlador._girar`).
- El 31/10 un servo de prueba en A0 no obedecía, aunque el pulso medido en el pin era
  correcto. Se sospechó del GND común, y el usuario lo unió; falta confirmar si el motor
  obedece. Sin GND común, un servo tiembla o se mueve solo y no sigue las órdenes.

## Garra (06/11)

La garra del modelo 3D ya está en el simulador: tres MG90S para **muñeca**, **giro de muñeca**
y **apertura**. Todavía no se mueve en el brazo real: falta el firmware, con sus pines.

- **Cómo va armada** (medido en las piezas, ver `herramientas/exportar_modelo.py`):
  - La U de la muñeca (Bilek) abraza la punta del antebrazo, con un pasador de 6,8 mm en
    su agujero de 6,9 mm: ese es el eje de la muñeca, paralelo al del codo.
  - El servo del giro de muñeca va atornillado a la pared trasera de la mano, entre las
    dos placas, con su brazo contra la U.
  - El de la garra va parado sobre la placa de arriba y mueve dos engranajes.
  - Cada dedo es un paralelogramo: brazos de 20 mm, con pivotes a 16 mm, igual que los
    agujeros del dedo. Por eso los dedos se abren paralelos.
- **Medidas:** del pasador a la punta de los dedos hay 144 mm, casi como el antebrazo. La
  apertura va de 1 mm (0 %, cerrada) a 29 mm (100 %, abierta).
- **Ubicación aproximada:** el MG90S de la muñeca se dibujó a ojo, según las fotos del
  modelo. No cuenta en los choques.
- **Choques:** con «Garra montada» activado, la mano cuenta en la protección como tres
  tubos (muñeca, palma y dedos). Si la mano está girada, el ancho de dedos y brazos queda
  en el plano del brazo y el tubo engorda.
- **Pose plegada de inicio:** solo es válida con la muñeca doblada (`muneca` = 90, el
  valor de fábrica). Recta, los dedos quedarían bajo la mesa.
- **En la página:** deslizadores «Muñeca», «Giro de muñeca» y «Garra», debajo del giro.
  Como el giro, van a su objetivo con velocidad limitada (`motor/control.py`,
  `AUXILIARES`), se detienen antes de chocar y no se mueven durante un plan.
- **La «punta»** de los joysticks y de «Ir a una pose» sigue siendo el eje de la muñeca.

## Rutinas (etapa C, 06/11)

Panel «Rutinas»: una serie de pasos que el brazo repite en orden (`motor/rutinas.py`).
Cada paso es una pose: cualquiera de hombro y codo (van juntos), giro, muñeca, giro de
muñeca y garra, más una espera. Se guardan en `simulador/datos/rutinas/<nombre>.json`.

- **Orden dentro de un paso:** primero el giro y la mano, después el brazo. Para no rozar
  nada, un paso por movimiento: subir, girar, bajar.
- **Antes de arrancar se revisa entera** sin mover nada («Comprobar»), con los mismos
  planes que «Ir a una pose». Si un paso es imposible o chocaría, no arranca y dice cuál.
- **Mientras corre:** se rechazan las órdenes manuales («Ir», giro, mano, calibración).
  Tocar un joystick o «Detener» la corta.
- **Grabar:** «Nueva», llevar el brazo a cada pose (joysticks, deslizadores) y «Agregar
  la pose actual como paso». Se reordenan con ↑ y se quitan con ×.
- **Ejemplo `cajita`** (12 pasos, unos 45 s): agarra una cajita de unos 20 mm de ancho a
  210 mm del hombro, girado −40°, y la deja girado +40°. La caja no se dibuja: es el
  movimiento. Mano vertical hacia abajo; las puntas de los dedos bajan hasta 25 mm de la
  mesa, que es lo más bajo con el margen de 15 mm. Las poses salen de la cinemática
  inversa (`inversa`) sobre la config del 06/11; se probó entera en simulación.
- **Con el brazo real habilitado** también lo mueve, igual que los joysticks. La mano
  todavía no tiene servos conectados.

## Convenciones

- Unidades: mm, grados, segundos. Origen en la mesa bajo el eje del hombro; x hacia el
  frente, y hacia arriba.
- **Ángulos mecánicos, no del servo.** Hombro = inclinación del **tramo recto de la pieza
  gris** respecto a la mesa (90 = vertical; se mide con el inclinómetro del celular apoyado
  en esa cara plana). Codo = giro del antebrazo respecto a ese tramo recto (−90 =
  perpendicular hacia adelante). La relación con los pulsos de cada servo se mide en la
  etapa B; no se supone que 90° del servo sea vertical.
- La pieza gris = tramo recto (eje del hombro → doblez) + tramo inclinado 65° hacia
  adelante respecto al recto (doblez → eje del codo).
- La «punta» es el eje de la muñeca (donde irá el SG90), a 140 mm del codo.
- Vista 3D: Y hacia arriba, X hacia el frente del brazo; `giro` positivo = antihorario
  visto desde arriba.
- Reposo = pose física del 28/10 (tramo recto vertical, antebrazo horizontal hacia
  adelante): hombro 90°, codo −91°. Se dedujo de la pose que el usuario igualó en el
  simulador con el modelo anterior (72°/−73° medidos sobre la línea eje a eje).

## Medidas

Desde el 30/10 salen del modelo 3D (sección anterior), con la pieza gris acortada como la
real (~152 mm de eje a eje, estimado). Las que se usaban antes quedaron
en `datos/config-antes-modelo-3d.json`. Diferencias principales: 200 mm de eje a eje
(antes 186), eje del hombro a 110 mm (antes 100) y antebrazo de 140 mm hasta el eje de
la muñeca (antes 155 hasta el extremo).

Historial: del usuario el 28/10 (con cinta, aproximadas): base azul 70 mm de alto; pieza gris
17 cm con un tramo inclinado de 6 cm a 30°, y 175 mm de eje a eje (de ahí el tramo
recto de 120 mm); antebrazo 155 mm del eje del codo a la punta (20 cm la pieza entera);
grosores 50 y 40 mm. Luego el usuario las ajustó mirando el simulador contra el brazo y
las dio por correctas: eje del hombro a 100 mm de la mesa, tramo recto 145 mm, tramo
inclinado 70 mm a 65° (186 mm de eje a eje), base de 68 mm de alto que va 127 mm por
delante y 93 mm por detrás de la vertical del eje del hombro. Se editan en la página (panel «Medidas y
límites»); se guardan en `simulador/datos/config.json`. La configuración del primer
modelo quedó en `datos/config-modelo-anterior.json`.

## Decisiones

- Toda la matemática y la seguridad viven en `simulador/motor/` (Python, con pruebas);
  la página solo dibuja y envía órdenes. Así no hay dos copias que se desincronicen.
- Trayectorias de quinto grado con hombro y codo sincronizados (empiezan y terminan
  juntos, sin tirones). Si una muestra tocaría la mesa o la base, el codo se flexiona lo
  mínimo y con antelación; si no alcanza, el movimiento se **rechaza** explicando dónde.
- Con los joysticks, si el siguiente paso tocaría algo:
  - Si es el hombro el que baja, el codo se flexiona. Si en ese ciclo no alcanza (con el
    antebrazo casi vertical, flexionar apenas sube la punta), el hombro espera mientras
    el codo abre espacio.
  - Si nada sirve, el brazo avanza **justo hasta el límite** y se queda ahí.
  - Antes se paraba un paso antes, avanzaba a tirones y el aviso parpadeaba (corregido
    el 30/10).
- El aviso se dibuja encima de la vista y dura al menos 0,8 s: aparecer o desaparecer
  no cambia el tamaño del dibujo.
- Joysticks por velocidad con parada automática si dejan de llegar órdenes (0,3 s).
  Modo «Punta»: un joystick mueve la punta en x/y y el servidor reparte hombro y codo.
- El dibujo muestra la posición **ordenada** (simulada), no medida.

## Pendiente para la etapa B (anotado el 28/10)

- **Arranque automático a la pose inicial** (el brazo se mueve al transportarlo): el
  MG995 no informa su posición, así que el primer pulso lo lleva de golpe a la pose
  pedida. Opciones: traba de transporte que lo mantenga en reposo (inmediato), y leer el
  potenciómetro interno de cada servo (un cable por servo a A3/A6/A7 con divisor) para
  arrancar desde la posición real y llegar despacio.
- Abrir el puerto serie reinicia el Nano (DTR): no debe repetir el arranque con un salto.
  Con la lectura de potenciómetros se resuelve; si no, condensador de 10 µF entre RESET y GND.
- Calibración por servo con tabla de 3 puntos (pulso → ángulo real medido con el
  inclinómetro del celular), límites por servo y por articulación, velocidad/aceleración
  por articulación.
- Alineación de los hombros si se desarman: ver «Cómo realinear los hombros».
