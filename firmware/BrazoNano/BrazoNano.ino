// Firmware del brazo para el simulador (etapa B1: calibración y pose de inicio).
//
// Al encender: si hay una pose de inicio guardada en la EEPROM, activa los
// servos ahí (primero los dos hombros a la vez, luego el codo). Si no la hay,
// arranca SIN señal y no mueve nada. Sin señal, el MG995 queda trabado por sus
// engranajes, así que si se apagó en la pose de inicio, al encender no salta.
// El servidor decide qué servo activar; aquí solo hay límites duros de pulso
// y movimiento con velocidad y aceleración limitadas, como última barrera.
//
// El giro (4.º servo) nunca se activa solo: la pose de inicio son hombros y codo,
// y el giro arranca sin señal hasta que el servidor lo habilita. Mueve todo el
// brazo, así que va más despacio y se activa con pulsos sueltos, que le dan poca
// fuerza, en lugar de saltar.
//
// Órdenes por serie (115200 baudios, una por línea):
//   A <servo> <us>   activar el servo en ese pulso (el primer pulso salta ahí)
//   S <servo> <us>   nuevo objetivo; si está activo va hacia él suave, si está
//                    suelto se activa ahí (igual que A)
//   D <servo>        soltar un servo (deja de recibir pulsos)
//   X                soltar todos
//   G <us0> <us1> <us2>  guardar la pose de inicio en la EEPROM
//   B                borrar la pose de inicio (volver a arrancar sin señal)
//   ?                volver a informar la pose de inicio
// Servos: 0 = hombro izquierdo (A1), 1 = hombro derecho (A2), 2 = codo (A0),
// 3 = giro (D9). G guarda solo los tres primeros.
// Informe cada 100 ms: E <activo0> <us0> <activo1> <us1> <activo2> <us2> <activo3> <us3>
// Al arrancar y al guardar/borrar: INICIO <us0> <us1> <us2>  o  INICIO -

#include <EEPROM.h>
#include <Servo.h>

const byte NUM = 4;
const byte NUM_INICIO = 3;  // la pose de inicio: hombros y codo
const byte GIRO = 3;
const byte PINES[NUM] = {A1, A2, A0, 9};

// Giro: ±54° que eligió el usuario, unos 900-2100 µs en un servo de 180°
const int US_MIN[NUM] = {700, 700, 700, 900};
const int US_MAX[NUM] = {2300, 2300, 2300, 2100};
// us/s: unos 39°/s los del brazo (subido de 300 el 28/10 a pedido del usuario), 11°/s el giro
const float VMAX[NUM] = {420, 420, 420, 120};
const float AMAX[NUM] = {840, 840, 840, 240};  // us/s²

const byte MARCA_INICIO = 0xB7;  // EEPROM[0]; luego 3 pulsos de 2 bytes

const unsigned long PERIODO = 20;   // ms entre actualizaciones
const unsigned long INFORME = 100;  // ms entre informes

Servo servos[NUM];
float pos[NUM];
float vel[NUM];
float objetivo[NUM];
bool activo[NUM];

char linea[32];
byte largo = 0;
unsigned long ultimoPaso = 0;
unsigned long ultimoInforme = 0;

void activar(byte i, int us) {
  if (i == GIRO && !activo[i]) {
    // Unos 3 s; mientras tanto los demás servos sostienen su último pulso
    for (byte n = 0; n < 25; n++) {
      digitalWrite(PINES[i], HIGH);
      delayMicroseconds(us);
      digitalWrite(PINES[i], LOW);
      delay(120);
    }
  }
  pos[i] = objetivo[i] = us;
  vel[i] = 0;
  servos[i].writeMicroseconds(us);
  if (!activo[i]) servos[i].attach(PINES[i]);
  activo[i] = true;
}

void soltar(byte i) {
  if (activo[i]) servos[i].detach();
  digitalWrite(PINES[i], LOW);
  activo[i] = false;
  vel[i] = 0;
}

bool leerInicio(int pulsos[NUM_INICIO]) {
  if (EEPROM.read(0) != MARCA_INICIO) return false;
  for (byte i = 0; i < NUM_INICIO; i++) {
    EEPROM.get(1 + 2 * i, pulsos[i]);
    if (pulsos[i] < US_MIN[i] || pulsos[i] > US_MAX[i]) return false;
  }
  return true;
}

void informarInicio() {
  int pulsos[NUM_INICIO];
  Serial.print("INICIO");
  if (leerInicio(pulsos)) {
    for (byte i = 0; i < NUM_INICIO; i++) {
      Serial.print(' ');
      Serial.print(pulsos[i]);
    }
    Serial.println();
  } else {
    Serial.println(" -");
  }
}

void guardarInicio(char *p) {
  int pulsos[NUM_INICIO];
  char *fin;
  for (byte i = 0; i < NUM_INICIO; i++) {
    long us = strtol(p, &fin, 10);
    if (fin == p || us < US_MIN[i] || us > US_MAX[i]) return;
    pulsos[i] = us;
    p = fin;
  }
  for (byte i = 0; i < NUM_INICIO; i++) EEPROM.put(1 + 2 * i, pulsos[i]);
  EEPROM.update(0, MARCA_INICIO);
  informarInicio();
}

void procesar(char *cmd) {
  char tipo = cmd[0];
  if (tipo == 'X') {
    for (byte i = 0; i < NUM; i++) soltar(i);
    return;
  }
  if (tipo == 'G') {
    guardarInicio(cmd + 1);
    return;
  }
  if (tipo == 'B') {
    EEPROM.update(0, 0xFF);
    informarInicio();
    return;
  }
  if (tipo == '?') {
    informarInicio();
    return;
  }
  char *p = cmd + 1;
  char *fin;
  long i = strtol(p, &fin, 10);
  if (fin == p || i < 0 || i >= NUM) return;
  if (tipo == 'D') {
    soltar(i);
    return;
  }
  p = fin;
  long us = strtol(p, &fin, 10);
  if (fin == p) return;
  us = constrain(us, US_MIN[i], US_MAX[i]);
  if (tipo == 'A') {
    activar(i, us);
  } else if (tipo == 'S') {
    if (activo[i]) objetivo[i] = us;
    else activar(i, us);
  }
}

void leerSerie() {
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\n' || ch == '\r') {
      linea[largo] = 0;
      if (largo > 0) procesar(linea);
      largo = 0;
    } else if (largo < sizeof(linea) - 1) {
      linea[largo++] = ch;
    }
  }
}

void avanzar(byte i, float dt) {
  float error = objetivo[i] - pos[i];
  // Velocidad que todavía permite frenar a tiempo: v = sqrt(2·a·d)
  float vFreno = sqrt(2 * AMAX[i] * fabs(error));
  float vDeseada = constrain(error > 0 ? vFreno : -vFreno, -VMAX[i], VMAX[i]);
  vel[i] += constrain(vDeseada - vel[i], -AMAX[i] * dt, AMAX[i] * dt);
  pos[i] += vel[i] * dt;
  if (fabs(objetivo[i] - pos[i]) < 1 && fabs(vel[i]) < AMAX[i] * dt) {
    pos[i] = objetivo[i];
    vel[i] = 0;
  }
  servos[i].writeMicroseconds((int)(pos[i] + 0.5));
}

void informar() {
  Serial.print('E');
  for (byte i = 0; i < NUM; i++) {
    Serial.print(' ');
    Serial.print(activo[i] ? 1 : 0);
    Serial.print(' ');
    Serial.print((int)(pos[i] + 0.5));
  }
  Serial.println();
}

void setup() {
  for (byte i = 0; i < NUM; i++) {
    pinMode(PINES[i], OUTPUT);
    digitalWrite(PINES[i], LOW);
    pos[i] = objetivo[i] = 1472;
    vel[i] = 0;
    activo[i] = false;
  }
  Serial.begin(115200);
  Serial.println("LISTO BrazoNano 6");
  int inicio[NUM_INICIO];
  if (leerInicio(inicio)) {
    // Hombros juntos (espejados, nunca uno solo) y después el codo
    activar(0, inicio[0]);
    activar(1, inicio[1]);
    delay(300);
    activar(2, inicio[2]);
  }
  informarInicio();
  ultimoPaso = ultimoInforme = millis();
}

void loop() {
  leerSerie();
  unsigned long ahora = millis();
  if (ahora - ultimoPaso >= PERIODO) {
    float dt = (ahora - ultimoPaso) / 1000.0;
    ultimoPaso = ahora;
    for (byte i = 0; i < NUM; i++) {
      if (activo[i]) avanzar(i, dt);
    }
  }
  if (ahora - ultimoInforme >= INFORME) {
    ultimoInforme = ahora;
    informar();
  }
}
