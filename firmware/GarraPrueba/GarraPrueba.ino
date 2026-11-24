// GarraPrueba 1: prueba de los 3 MG90S de la garra, con o sin el brazo.
//
// Usa los pines que tendrá la garra en BrazoNano (A0-A2 son el brazo y D9 el giro):
//   servo 0 = muñeca: elevación y declive  -> D10
//   servo 1 = cuello: giro de la muñeca    -> D11
//   servo 2 = agarre: abre y cierra        -> D12
//
// Arranca SIN señal: nada se mueve hasta que actives un servo con A.
// Alimentación: fuente externa de 5 a 6 V (un MG90S aguanta hasta 6 V), nunca el
// 5V del Nano, y el GND de la fuente unido al GND del Nano.
//
// Monitor serie a 115200 baudios, con «Nueva línea» como fin de línea:
//   A <servo> <us>   activar en ese pulso (el primer pulso salta ahí)
//   S <servo> <us>   ir suave a ese pulso
//   + <servo>        subir 20 us (unos 2 grados)
//   - <servo>        bajar 20 us
//   D <servo>        soltar ese servo
//   X                soltar todos
//   ?                estado
// Ejemplo: «A 2 1500» activa el agarre en el centro y «+ 2» lo mueve un poco.

#include <Servo.h>

const byte NUM = 3;
const byte PINES[NUM] = {10, 11, 12};
const char *const NOMBRES[NUM] = {"muneca", "cuello", "agarre"};

// Límites duros: rango típico de un MG90S, NO medido en esta garra
const int US_MIN = 600;
const int US_MAX = 2400;
const int PASO = 20;               // us por cada + o -
const float VELOCIDAD = 300;       // us/s
const unsigned long PERIODO = 20;  // ms entre actualizaciones

Servo servos[NUM];
bool activo[NUM];
float pos[NUM];
int objetivo[NUM];
unsigned long ultimo = 0;

char linea[24];
byte largo = 0;

void informar(byte i) {
  Serial.print(i);
  Serial.print(' ');
  Serial.print(NOMBRES[i]);
  Serial.print(' ');
  if (!activo[i]) {
    Serial.println("suelto");
    return;
  }
  Serial.print((int)(pos[i] + 0.5));
  Serial.print(" -> ");
  Serial.println(objetivo[i]);
}

void activar(byte i, int us) {
  us = constrain(us, US_MIN, US_MAX);
  pos[i] = us;
  objetivo[i] = us;
  servos[i].writeMicroseconds(us);  // antes de attach: el primer pulso ya es este
  if (!activo[i]) servos[i].attach(PINES[i]);
  activo[i] = true;
}

void soltar(byte i) {
  if (activo[i]) servos[i].detach();
  activo[i] = false;
  digitalWrite(PINES[i], LOW);
}

void ejecutar() {
  char orden = 0;
  int servo = -1, us = 0;
  int n = sscanf(linea, " %c %d %d", &orden, &servo, &us);
  if (n < 1) return;
  orden = toupper(orden);

  if (orden == 'X') {
    for (byte i = 0; i < NUM; i++) soltar(i);
    Serial.println("todos sueltos");
    return;
  }
  if (orden == '?') {
    for (byte i = 0; i < NUM; i++) informar(i);
    return;
  }
  if (n < 2 || servo < 0 || servo >= NUM) {
    Serial.println("falta el servo: 0 muneca, 1 cuello, 2 agarre");
    return;
  }

  byte i = servo;
  if (orden == 'D') {
    soltar(i);
    informar(i);
    return;
  }
  if (orden == 'A' && n == 3) {
    activar(i, us);
    informar(i);
    return;
  }
  if (orden != 'S' && orden != '+' && orden != '-') {
    Serial.println("orden no valida (A, S, +, -, D, X, ?)");
    return;
  }
  if (!activo[i]) {
    Serial.println("esta suelto: activalo primero con A");
    return;
  }
  int nuevo = objetivo[i];
  if (orden == 'S' && n == 3) nuevo = us;
  else if (orden == '+') nuevo += PASO;
  else if (orden == '-') nuevo -= PASO;
  else {
    Serial.println("falta el pulso: S <servo> <us>");
    return;
  }
  if (nuevo < US_MIN || nuevo > US_MAX) Serial.println("limite del sketch");
  objetivo[i] = constrain(nuevo, US_MIN, US_MAX);
  informar(i);
}

void setup() {
  for (byte i = 0; i < NUM; i++) {
    pinMode(PINES[i], OUTPUT);
    digitalWrite(PINES[i], LOW);
  }
  Serial.begin(115200);
  Serial.println("GarraPrueba 1: todo suelto. Ej.: A 2 1500, luego + 2 o - 2");
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      linea[largo] = 0;
      if (largo > 0) ejecutar();
      largo = 0;
    } else if (largo < sizeof(linea) - 1) {
      linea[largo++] = c;
    }
  }

  unsigned long ahora = millis();
  if (ahora - ultimo < PERIODO) return;
  float maximo = VELOCIDAD * (ahora - ultimo) / 1000.0;
  ultimo = ahora;
  for (byte i = 0; i < NUM; i++) {
    if (!activo[i]) continue;
    float falta = objetivo[i] - pos[i];
    if (falta == 0) continue;
    bool llega = fabs(falta) <= maximo;
    pos[i] = llega ? objetivo[i] : pos[i] + (falta > 0 ? maximo : -maximo);
    servos[i].writeMicroseconds((int)(pos[i] + 0.5));
    if (llega) informar(i);
  }
}
