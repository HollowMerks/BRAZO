"use strict";
// Página del simulador: dibuja lo que manda el servidor y le envía órdenes.
// La geometría y la seguridad se calculan en el servidor (motor/), no aquí.

const $ = (sel) => document.querySelector(sel);
const NS = "http://www.w3.org/2000/svg";
const fmt = (n, dec = 1) => n.toFixed(dec).replace(".", ",").replace("-", "−");

let cfg = null;
let estado = null;
let modo = "articulaciones";
let previa = null; // plan de vista previa mientras se ajustan los deslizadores

async function api(ruta, datos, metodo = "POST") {
  const r = await fetch(ruta, {
    method: metodo,
    headers: { "Content-Type": "application/json" },
    body: datos === undefined ? undefined : JSON.stringify(datos),
  });
  const json = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(json.error || "Error del servidor"), { datos: json });
  return json;
}

// ---------- Dibujo ----------

const lienzo = $("#lienzo");
const capa = {};

function el(nombre, atributos, padre) {
  const e = document.createElementNS(NS, nombre);
  for (const [k, v] of Object.entries(atributos)) e.setAttribute(k, v);
  padre.appendChild(e);
  return e;
}

function construirEscena() {
  lienzo.replaceChildren();
  const L = cfg.brazo_recto + cfg.brazo_inclinado + cfg.largo_antebrazo;
  // Lo que queda de la caja bajo el plano del brazo (depende del giro de la torreta)
  const [b0, b1] = cfg.base_plano;
  const x0 = Math.min(b0 - 30, -L * 0.7), x1 = Math.max(L * 1.1, b1 + 30);
  const y0 = -25, y1 = cfg.altura_hombro + L + 25;
  lienzo.setAttribute("viewBox", `${x0} ${-y1} ${x1 - x0} ${y1 - y0}`);
  const g = el("g", { transform: "scale(1,-1)" }, lienzo);

  const rejilla = el("g", { class: "rejilla" }, g);
  for (let x = Math.ceil(x0 / 50) * 50; x <= x1; x += 50) el("line", { x1: x, y1: 0, x2: x, y2: y1 }, rejilla);
  for (let y = 50; y <= y1; y += 50) el("line", { x1: x0, y1: y, x2: x1, y2: y }, rejilla);

  const mesa = el("g", { class: "mesa" }, g);
  el("line", { x1: x0, y1: 0, x2: x1, y2: 0 }, mesa);
  for (let x = Math.ceil(x0 / 12) * 12; x < x1; x += 12) el("line", { x1: x, y1: 0, x2: x - 10, y2: -10, class: "raya" }, mesa);
  el("line", { x1: x0, y1: cfg.margen, x2: x1, y2: cfg.margen, class: "margen" }, g);
  capa.base = el("rect", { x: b0, y: 0, width: b1 - b0, height: cfg.base_alto, rx: 4, class: "base" }, g);
  el("line", { x1: 0, y1: 0, x2: 0, y2: cfg.altura_hombro, class: "plomada" }, g);

  // Dónde está el brazo real según sus pulsos y la calibración (solo con el puente apagado)
  capa.real = el("g", { class: "real-fantasma" }, g);
  capa.rBrazo = el("polyline", {}, capa.real);
  capa.rAnte = el("line", {}, capa.real);
  capa.rPunta = el("circle", { r: 5 }, capa.real);
  capa.traza = el("polyline", { class: "traza" }, g);
  capa.fantasma = el("g", { class: "fantasma" }, g);
  capa.fBrazo = el("polyline", {}, capa.fantasma);
  capa.fAnte = el("line", {}, capa.fantasma);

  capa.brazo = el("g", {}, g);
  // El grosor dibujado es el mismo que usa el cálculo de choques
  capa.cBrazo = el("polyline", { class: "cuerpo brazo", "stroke-width": cfg.grosor_brazo }, capa.brazo);
  capa.cAnte = el("line", { class: "cuerpo antebrazo", "stroke-width": cfg.grosor_antebrazo }, capa.brazo);
  capa.eBrazo = el("polyline", { class: "eje brazo" }, capa.brazo);
  capa.eAnte = el("line", { class: "eje antebrazo" }, capa.brazo);
  capa.hombro = el("circle", { r: 7, class: "articulacion fija" }, capa.brazo);
  capa.codo = el("circle", { r: 6, class: "articulacion" }, capa.brazo);
  capa.punta = el("circle", { r: 5, class: "punta" }, capa.brazo);
  // Garra: muñeca, palma y dedos con el grosor que usa el cálculo de choques
  capa.mano = el("g", {}, capa.brazo);
  capa.cMuneca = el("line", { class: "cuerpo mano", "stroke-width": 26 }, capa.mano);
  capa.cPalma = el("line", { class: "cuerpo mano" }, capa.mano);
  capa.cDedos = el("line", { class: "cuerpo mano" }, capa.mano);
  capa.eMano = el("polyline", { class: "eje mano" }, capa.mano);
}

const lista = (pts) => pts.map((p) => p.join(",")).join(" ");
function linea(e, a, b) {
  e.setAttribute("x1", a[0]); e.setAttribute("y1", a[1]);
  e.setAttribute("x2", b[0]); e.setAttribute("y2", b[1]);
}
function centro(e, p) { e.setAttribute("cx", p[0]); e.setAttribute("cy", p[1]); }

function dibujarBrazo(p, choque) {
  const brazo = lista([p.hombro, p.doblez, p.codo]);
  capa.cBrazo.setAttribute("points", brazo);
  capa.eBrazo.setAttribute("points", brazo);
  linea(capa.cAnte, p.codo, p.punta);
  linea(capa.eAnte, p.codo, p.punta);
  centro(capa.hombro, p.hombro);
  centro(capa.codo, p.codo);
  centro(capa.punta, p.punta);
  capa.mano.style.display = p.dedos ? "" : "none";
  if (p.dedos) {
    linea(capa.cMuneca, p.punta, p.base_mano);
    linea(capa.cPalma, p.base_mano, p.palma);
    linea(capa.cDedos, p.palma, p.dedos);
    capa.eMano.setAttribute("points", lista([p.punta, p.dedos]));
    const [rp, rd] = estado.mano.radios;
    capa.cPalma.setAttribute("stroke-width", 2 * rp);
    capa.cDedos.setAttribute("stroke-width", 2 * rd);
  }
  capa.brazo.classList.toggle("choque", choque);
}

function dibujarFantasma(p, traza, malo) {
  capa.fantasma.style.display = p ? "" : "none";
  capa.traza.style.display = traza ? "" : "none";
  if (p) {
    capa.fBrazo.setAttribute("points", lista([p.hombro, p.doblez, p.codo]));
    linea(capa.fAnte, p.codo, p.punta);
    capa.fantasma.classList.toggle("malo", malo);
  }
  if (traza) capa.traza.setAttribute("points", lista(traza));
}

// ---------- Vista 3D o lateral ----------

let vista3d = null; // la crea vista3d.js cuando termina de cargar las piezas
const vistas = $("#vistas");

function mostrarVista(v, recordar = true) {
  $("#vista3d").hidden = v !== "3d";
  lienzo.style.display = v === "lateral" ? "" : "none";
  for (const b of vistas.querySelectorAll("button")) {
    b.classList.toggle("activo", b.dataset.vista === v);
    b.setAttribute("aria-checked", String(b.dataset.vista === v));
  }
  if (recordar) {
    try { localStorage.setItem("brazo-vista", v); } catch { /* sin almacenamiento: no pasa nada */ }
  }
}

function sin3d(motivo) {
  const b = vistas.querySelector('[data-vista="3d"]');
  b.disabled = true;
  b.title = motivo;
  $("#vista3d").innerHTML = "";
  mostrarVista("lateral", false);
}

vistas.addEventListener("click", (ev) => {
  const b = ev.target.closest("button");
  if (b && !b.disabled) mostrarVista(b.dataset.vista);
});
window.addEventListener("vista3d-lista", () => {
  vista3d = window.vista3d;
  const b = vistas.querySelector('[data-vista="3d"]');
  b.disabled = false; // por si llegó después del plazo
  b.title = "";
  if (cfg) vista3d.configurar(cfg);
  actualizar();
});
window.addEventListener("vista3d-error", (ev) => sin3d("No se pudo cargar la vista 3D: " + ev.detail));
// Navegadores sin módulos o sin WebGL: si en 30 s no llegó, queda la vista lateral
setTimeout(() => { if (window.vista3d === undefined) sin3d("La vista 3D no cargó"); }, 30000);
{
  let guardada = "3d";
  try { guardada = localStorage.getItem("brazo-vista") || "3d"; } catch { /* idem */ }
  mostrarVista(guardada === "lateral" ? "lateral" : "3d", false);
}

// ---------- Estado en vivo ----------

function actualizar() {
  if (!estado || !cfg) return;
  if (estado.version_config !== cfg.version) {
    cargarConfig();
    return;
  }
  dibujarBrazo(estado.puntos, estado.holgura < 0);
  // La torreta gira y cambia qué parte de la caja queda bajo el brazo
  capa.base.setAttribute("x", estado.base_plano[0]);
  capa.base.setAttribute("width", estado.base_plano[1] - estado.base_plano[0]);

  $("#lec-hombro").textContent = fmt(estado.hombro) + "°";
  $("#lec-codo").textContent = fmt(estado.codo) + "°";
  const hol = $("#lec-holgura");
  hol.textContent = fmt(estado.holgura, 0) + " mm";
  hol.classList.toggle("choque", estado.holgura < 0);
  hol.classList.toggle("justo", estado.holgura >= 0 && estado.holgura < 15);
  hol.title = estado.donde;

  let guia = null; // pose pedida (vista previa o plan en curso) y el recorrido de la punta
  if (previa) guia = { p: previa.final || previa.solicitado, traza: previa.traza, malo: !previa.valido };
  else if (estado.plan) guia = { p: estado.plan.final, traza: estado.plan.traza, malo: false };
  dibujarFantasma(guia && guia.p, guia && guia.traza, Boolean(guia && guia.malo));

  pintarReal();
  pintarGiro();
  pintarMano();
  pintarRutina();
  const r = estado.real;
  const verReal = r && r.puntos && !r.habilitado;
  capa.real.style.display = verReal ? "" : "none";
  if (verReal) {
    capa.rBrazo.setAttribute("points", lista([r.puntos.hombro, r.puntos.doblez, r.puntos.codo]));
    linea(capa.rAnte, r.puntos.codo, r.puntos.punta);
    centro(capa.rPunta, r.puntos.punta);
  }
  if (vista3d) {
    const cadena = (p) => [p.hombro, p.doblez, p.codo, p.punta];
    vista3d.actualizar({
      estado,
      fantasma: guia && guia.p ? { puntos: cadena(guia.p), malo: guia.malo } : null,
      traza: guia && guia.traza,
      real: verReal ? cadena(r.puntos) : null,
    });
  }

  mostrarAviso(estado.aviso);

  if (!previa && !arrastrando) ponerDeslizadores(estado.hombro, estado.codo);
}

// Cada aviso se ve al menos un rato: si el servidor lo quita y lo vuelve a poner
// seguido, no parpadea
let avisoVisto = { texto: "", hasta: 0 };
function mostrarAviso(texto, duracion = 800) {
  const ahora = Date.now();
  if (texto) avisoVisto = { texto, hasta: ahora + duracion };
  else if (ahora < avisoVisto.hasta) texto = avisoVisto.texto;
  const aviso = $("#aviso");
  aviso.hidden = !texto;
  if (aviso.textContent !== texto) aviso.textContent = texto;
  aviso.classList.toggle("malo", texto.startsWith("Detenido"));
}

let avisoLocal = { texto: "", malo: false, hasta: 0 }; // mensajes de habilitar, visibles unos segundos

function pintarReal() {
  const r = estado.real;
  const caja = $("#real");
  caja.hidden = !r;
  const chip = $("#conexion");
  if (chip.className !== "chip mal") {
    chip.textContent = r && r.habilitado ? "Brazo real siguiendo al simulador" : "Simulación";
    chip.className = r && r.habilitado ? "chip real" : "chip ok";
  }
  if (!r) return;
  caja.classList.toggle("encendido", r.habilitado);
  $("#real-estado").textContent = r.habilitado ? "sigue al simulador"
    : r.puntos ? `apagado · real en hombro ${fmt(r.hombro)}°, codo ${fmt(r.codo)}° (línea naranja)` : "apagado";
  $("#real-btn").textContent = r.habilitado ? "Deshabilitar" : "Habilitar";
  const aviso = $("#real-aviso");
  const local = Date.now() < avisoLocal.hasta ? avisoLocal : null;
  const texto = r.aviso || (local ? local.texto : "");
  aviso.hidden = !texto;
  aviso.textContent = texto;
  aviso.className = r.aviso || (local && local.malo) ? "info malo" : "info";
}

$("#real-btn").addEventListener("click", async () => {
  try {
    if (estado.real && estado.real.habilitado) {
      await api("/api/real/deshabilitar", {});
      return;
    }
    const r = await api("/api/real/habilitar", {});
    if (r.cambios.length) {
      avisoLocal = { texto: "Ajustado al brazo real: " + r.cambios.join(" · "), malo: false, hasta: Date.now() + 10000 };
    }
  } catch (e) {
    avisoLocal = { texto: e.message, malo: true, hasta: Date.now() + 10000 };
  }
  pintarReal();
});

// ---------- Giro de la torreta ----------

const sGiro = $("#s-giro");
let arrastrandoGiro = false, giroEnVuelo = false, giroPendiente = false;
let giroLocal = { texto: "", hasta: 0 };

function pintarGiro() {
  $("#v-giro").textContent = fmt(estado.giro) + "°";
  if (!arrastrandoGiro && !giroEnVuelo) sGiro.value = estado.giro_objetivo;
  const g = estado.giro_real;
  const caja = $("#giro-real");
  caja.hidden = !g;
  if (!g) return;
  caja.classList.toggle("encendido", g.habilitado);
  const pulso = g.us === null ? "" : ` · ${g.us} µs`;
  $("#giro-estado").textContent = g.arrancando ? "activando el servo, unos 3 s…"
    : !g.responde ? "el Nano no responde; ¿tiene BrazoNano 6?"
    : g.habilitado ? "sigue al simulador" + pulso
    : g.activo ? "apagado · sostenido" + pulso : "apagado · suelto";
  $("#giro-btn").textContent = g.habilitado ? "Deshabilitar" : "Habilitar";
  $("#giro-soltar").disabled = !g.activo;
  const aviso = $("#giro-aviso");
  const local = Date.now() < giroLocal.hasta ? giroLocal.texto : "";
  aviso.hidden = !(g.aviso || local);
  aviso.textContent = g.aviso || local;
}

async function pedirGiro() {
  giroPendiente = true;
  if (giroEnVuelo) return;
  giroEnVuelo = true;
  while (giroPendiente) {
    giroPendiente = false;
    try { await api("/api/giro", { angulo: +sGiro.value }); }
    catch (e) { mostrarAviso(e.message, 4000); }
  }
  giroEnVuelo = false;
}

sGiro.addEventListener("input", pedirGiro);
sGiro.addEventListener("pointerdown", () => { arrastrandoGiro = true; });
for (const t of ["pointerup", "pointercancel"]) sGiro.addEventListener(t, () => { arrastrandoGiro = false; });
$("#btn-centrar").addEventListener("click", () => { sGiro.value = 0; pedirGiro(); });

async function ordenGiro(ruta) {
  try { await api(ruta, {}); }
  catch (e) { giroLocal = { texto: e.message, hasta: Date.now() + 8000 }; }
}
$("#giro-btn").addEventListener("click", () => {
  ordenGiro(estado.giro_real && estado.giro_real.habilitado ? "/api/giro/deshabilitar" : "/api/giro/habilitar");
});
$("#giro-soltar").addEventListener("click", () => ordenGiro("/api/giro/soltar"));

// ---------- Garra: muñeca, giro de muñeca y apertura ----------

const deslizadoresMano = [...document.querySelectorAll("#mano input[type=range]")];
const manoArrastre = new Set();
let manoEnVuelo = false, manoPendiente = {};

function textoMano(nombre, valor) {
  if (nombre !== "garra") return fmt(valor) + "°";
  return `${fmt(valor, 0)} % · ${fmt(cfg.garra_apertura * valor / 100, 0)} mm`;
}

function pintarMano() {
  const m = estado.mano;
  $("#mano").hidden = !m || !m.montada;
  if (!m || !m.montada) return;
  for (const s of deslizadoresMano) {
    const n = s.dataset.articulacion;
    $("#v-" + n).textContent = textoMano(n, m[n]);
    if (!manoArrastre.has(n) && !(n in manoPendiente) && !manoEnVuelo) s.value = m.objetivos[n];
  }
}

async function pedirMano(nombre, valor) {
  manoPendiente[nombre] = valor;
  if (manoEnVuelo) return;
  manoEnVuelo = true;
  while (Object.keys(manoPendiente).length) {
    const datos = manoPendiente;
    manoPendiente = {};
    try { await api("/api/mano", datos); }
    catch (e) { mostrarAviso(e.message, 4000); }
  }
  manoEnVuelo = false;
}

for (const s of deslizadoresMano) {
  const n = s.dataset.articulacion;
  s.addEventListener("input", () => pedirMano(n, +s.value));
  s.addEventListener("pointerdown", () => manoArrastre.add(n));
  for (const t of ["pointerup", "pointercancel"]) s.addEventListener(t, () => manoArrastre.delete(n));
}

// ---------- Rutinas: pasos que el brazo repite en orden ----------

let rutina = { nombre: "", pasos: [], cambios: false };
let rutinaVista = ""; // para no redibujar la lista en cada estado

function resumenPaso(p) {
  const partes = [];
  if (p.hombro !== undefined) partes.push(`hombro ${fmt(p.hombro)}°, codo ${fmt(p.codo)}°`);
  if (p.giro !== undefined) partes.push(`giro ${fmt(p.giro)}°`);
  if (p.muneca !== undefined) partes.push(`muñeca ${fmt(p.muneca)}°`);
  if (p.giro_muneca !== undefined) partes.push(`giro de muñeca ${fmt(p.giro_muneca)}°`);
  if (p.garra !== undefined) partes.push(`garra ${fmt(p.garra, 0)} %`);
  if (p.espera) partes.push(`espera ${fmt(p.espera)} s`);
  return partes.join(" · ");
}

function pintarPasos() {
  const r = estado && estado.rutina;
  const activo = r && r.activa && r.nombre === rutina.nombre ? r.paso : 0;
  const clave = JSON.stringify([rutina.pasos, activo]);
  if (clave === rutinaVista) return;
  rutinaVista = clave;
  const lista = $("#r-pasos");
  lista.replaceChildren();
  rutina.pasos.forEach((p, i) => {
    const li = document.createElement("li");
    li.classList.toggle("activo", activo === i + 1);
    const texto = document.createElement("span");
    texto.textContent = `${i + 1}. ${p.nombre}`;
    const detalle = document.createElement("small");
    detalle.textContent = resumenPaso(p);
    texto.appendChild(detalle);
    const mover = document.createElement("div");
    mover.className = "mover";
    const subir = document.createElement("button");
    subir.textContent = "↑";
    subir.title = "Subir este paso";
    subir.disabled = i === 0;
    subir.onclick = () => { [rutina.pasos[i - 1], rutina.pasos[i]] = [rutina.pasos[i], rutina.pasos[i - 1]]; cambioRutina(); };
    const quitar = document.createElement("button");
    quitar.textContent = "×";
    quitar.title = "Quitar este paso";
    quitar.onclick = () => { rutina.pasos.splice(i, 1); cambioRutina(); };
    mover.append(subir, quitar);
    li.append(texto, mover);
    lista.appendChild(li);
  });
}

function cambioRutina() {
  rutina.cambios = true;
  infoRutina(rutina.pasos.length ? "Sin guardar." : "", false);
  pintarPasos();
}

function infoRutina(texto, malo) {
  $("#r-info").textContent = texto;
  $("#r-info").className = malo ? "info malo" : "info";
}

function pintarRutina() {
  const r = estado.rutina;
  if (!r) return;
  const caja = $("#r-estado");
  caja.textContent = r.activa ? `En marcha «${r.nombre}»: paso ${r.paso} de ${r.total}, ${r.descripcion}`
    : r.aviso ? `«${r.nombre}»: ${r.aviso}` : "Lista";
  caja.className = r.aviso && r.aviso !== "Terminada" && !r.activa ? "info malo" : "info";
  $("#r-ejecutar").disabled = r.activa || !rutina.pasos.length;
  $("#r-detener").disabled = !r.activa;
  pintarPasos();
}

async function listarRutinas(elegir) {
  const r = await api("/api/rutinas", undefined, "GET");
  const sel = $("#r-lista");
  sel.replaceChildren();
  const nombres = [...new Set([...r.rutinas, ...(rutina.nombre ? [rutina.nombre] : [])])].sort();
  for (const n of nombres) {
    const o = document.createElement("option");
    o.value = o.textContent = n;
    sel.appendChild(o);
  }
  if (elegir) sel.value = elegir;
  else if (rutina.nombre) sel.value = rutina.nombre;
  if (sel.value && sel.value !== rutina.nombre) await cargarRutina(sel.value);
}

async function cargarRutina(nombre) {
  try {
    const r = await api("/api/rutina/leer", { nombre });
    rutina = { nombre, pasos: r.pasos, cambios: false };
    infoRutina("", false);
  } catch (e) { infoRutina(e.message, true); }
  pintarPasos();
}

$("#panel-rutinas").addEventListener("toggle", (ev) => { if (ev.target.open) listarRutinas().catch((e) => infoRutina(e.message, true)); });
$("#r-lista").addEventListener("change", (ev) => {
  if (rutina.cambios && !confirm(`«${rutina.nombre}» tiene cambios sin guardar. ¿Cambiar de rutina igual?`)) {
    ev.target.value = rutina.nombre;
    return;
  }
  cargarRutina(ev.target.value);
});
$("#r-nueva").addEventListener("click", () => {
  const nombre = (prompt("Nombre de la rutina nueva (letras, números, - y _):") || "").trim();
  if (!nombre) return;
  rutina = { nombre, pasos: [], cambios: true };
  listarRutinas(nombre);
  infoRutina("Rutina nueva: agrega pasos y guárdala.", false);
  pintarPasos();
});
$("#r-borrar").addEventListener("click", async () => {
  if (!rutina.nombre || !confirm(`¿Borrar la rutina «${rutina.nombre}»?`)) return;
  try {
    await api("/api/rutina/borrar", { nombre: rutina.nombre });
    rutina = { nombre: "", pasos: [], cambios: false };
    await listarRutinas();
  } catch (e) { infoRutina(e.message, true); }
  pintarPasos();
});
$("#r-agregar").addEventListener("click", () => {
  if (!rutina.nombre) { infoRutina("Primero crea una rutina con «Nueva».", true); return; }
  const campo = $("#r-nombre-paso");
  const paso = { nombre: campo.value.trim() || `Paso ${rutina.pasos.length + 1}`,
    hombro: +estado.hombro.toFixed(1), codo: +estado.codo.toFixed(1), giro: +estado.giro.toFixed(1) };
  if (estado.mano && estado.mano.montada) {
    for (const k of ["muneca", "giro_muneca", "garra"]) paso[k] = +estado.mano[k].toFixed(1);
  }
  rutina.pasos.push(paso);
  campo.value = "";
  cambioRutina();
});
$("#r-comprobar").addEventListener("click", async () => {
  try {
    const r = await api("/api/rutina/comprobar", { pasos: rutina.pasos });
    if (r.problemas.length) infoRutina(r.problemas.join(" · "), true);
    else infoRutina(`Sin problemas desde la pose actual · unos ${fmt(r.segundos, 0)} s`, false);
  } catch (e) { infoRutina(e.message, true); }
});
$("#r-guardar").addEventListener("click", async () => {
  try {
    const r = await api("/api/rutina/guardar", { nombre: rutina.nombre, pasos: rutina.pasos });
    rutina.pasos = r.pasos;
    rutina.cambios = false;
    infoRutina("Guardada.", false);
    await listarRutinas(rutina.nombre);
  } catch (e) { infoRutina(e.message, true); }
});
$("#r-ejecutar").addEventListener("click", async () => {
  previa = null; mostrarPrevia();
  try {
    const r = await api("/api/rutina/ejecutar", { nombre: rutina.nombre, pasos: rutina.pasos });
    infoRutina(`Unos ${fmt(r.segundos, 0)} s. Tocar un joystick o «Detener» la corta.`, false);
  } catch (e) { infoRutina(e.message, true); }
});
$("#r-detener").addEventListener("click", () => api("/api/rutina/detener", {}).catch(() => {}));

function conectar() {
  const chip = $("#conexion");
  const fuente = new EventSource("/api/eventos");
  fuente.onopen = () => { chip.textContent = "Simulación"; chip.className = "chip ok"; };
  fuente.onerror = () => { chip.textContent = "Sin conexión, reintentando…"; chip.className = "chip mal"; };
  fuente.onmessage = (ev) => { estado = JSON.parse(ev.data); actualizar(); };
}

let cargando = false;
async function cargarConfig() {
  if (cargando) return;
  cargando = true;
  try {
    cfg = await api("/api/config", undefined, "GET");
    construirEscena();
    if (vista3d) vista3d.configurar(cfg);
    configurarDeslizadores();
    llenarMedidas();
  } finally {
    cargando = false;
  }
  actualizar();
}

// ---------- Deslizadores: ir a una pose ----------

const sHombro = $("#s-hombro"), sCodo = $("#s-codo");
let arrastrando = false;

function configurarDeslizadores() {
  sHombro.min = cfg.hombro.minimo; sHombro.max = cfg.hombro.maximo;
  sCodo.min = cfg.codo.minimo; sCodo.max = cfg.codo.maximo;
  sGiro.min = cfg.torreta.minimo; sGiro.max = cfg.torreta.maximo;
  for (const s of deslizadoresMano) {
    const lim = cfg["lim_" + s.dataset.articulacion];
    s.min = lim.minimo; s.max = lim.maximo;
  }
}

function ponerDeslizadores(h, c) {
  sHombro.value = h; sCodo.value = c;
  $("#v-hombro").textContent = fmt(+sHombro.value) + "°";
  $("#v-codo").textContent = fmt(+sCodo.value) + "°";
}

let enVuelo = false, pendiente = false;
async function pedirPrevia() {
  pendiente = true;
  if (enVuelo) return;
  enVuelo = true;
  while (pendiente) {
    pendiente = false;
    const pose = { hombro: +sHombro.value, codo: +sCodo.value };
    try { previa = { ...(await api("/api/vista_previa", pose)), pose }; }
    catch (e) { previa = { valido: false, motivo: e.message, pose }; }
    mostrarPrevia();
  }
  enVuelo = false;
}

function mostrarPrevia() {
  const info = $("#info-plan");
  $("#btn-ir").disabled = !previa || !previa.valido;
  $("#btn-cancelar").disabled = !previa;
  if (!previa) { info.textContent = ""; info.className = "info"; return; }
  if (!previa.valido) {
    info.textContent = previa.motivo;
    info.className = "info malo";
  } else {
    info.textContent = `${fmt(previa.duracion)} s` + (previa.motivo ? ` · ${previa.motivo}` : "");
    info.className = previa.motivo ? "info corregido" : "info";
  }
  actualizar();
}

for (const s of [sHombro, sCodo]) {
  s.addEventListener("input", () => {
    $("#v-hombro").textContent = fmt(+sHombro.value) + "°";
    $("#v-codo").textContent = fmt(+sCodo.value) + "°";
    pedirPrevia();
  });
  s.addEventListener("pointerdown", () => { arrastrando = true; });
  s.addEventListener("pointerup", () => { arrastrando = false; });
}

$("#btn-ir").addEventListener("click", async () => {
  if (!previa || !previa.valido) return;
  try {
    const r = await api("/api/mover", previa.pose);
    if (!r.valido) { previa = { ...r, pose: previa.pose }; mostrarPrevia(); return; }
  } catch (e) { $("#info-plan").textContent = e.message; return; }
  previa = null;
  mostrarPrevia();
});
$("#btn-cancelar").addEventListener("click", () => { previa = null; mostrarPrevia(); });

$("#btn-reposo").addEventListener("click", async () => {
  previa = null; mostrarPrevia();
  const r = await api("/api/reposo").catch((e) => ({ valido: false, motivo: e.message }));
  if (!r.valido) mostrarAviso(r.motivo, 5000);
});
$("#btn-detener").addEventListener("click", () => api("/api/detener").catch(() => {}));

// ---------- Joysticks ----------

class Joystick {
  constructor(elemento) {
    this.e = elemento;
    this.perilla = elemento.querySelector(".perilla");
    this.id = null;
    this.x = 0;
    this.y = 0;
    this.dosEjes = false;
    this.e.addEventListener("pointerdown", (ev) => this.empezar(ev));
    this.e.addEventListener("pointermove", (ev) => this.mover(ev));
    for (const t of ["pointerup", "pointercancel", "lostpointercapture"]) {
      this.e.addEventListener(t, (ev) => this.soltar(ev));
    }
  }
  get activo() { return this.id !== null; }
  empezar(ev) {
    if (this.id !== null) return;
    this.id = ev.pointerId;
    this.e.setPointerCapture(ev.pointerId);
    this.e.classList.add("activo");
    this.mover(ev);
    ev.preventDefault();
  }
  mover(ev) {
    if (ev.pointerId !== this.id) return;
    const r = this.e.getBoundingClientRect();
    const rx = r.width / 2 - this.perilla.offsetWidth / 2;
    const ry = r.height / 2 - this.perilla.offsetHeight / 2;
    let dx = this.dosEjes ? (ev.clientX - (r.left + r.width / 2)) / rx : 0;
    let dy = (ev.clientY - (r.top + r.height / 2)) / ry;
    const m = Math.hypot(dx, dy);
    if (m > 1) { dx /= m; dy /= m; }
    this.perilla.style.transform = `translate(${dx * rx}px, ${dy * ry}px)`;
    // Zona muerta pequeña para que el pulgar en reposo no mueva nada
    const zona = 0.08;
    const f = (v) => (Math.abs(v) < zona ? 0 : (v - Math.sign(v) * zona) / (1 - zona));
    this.x = f(dx);
    this.y = -f(dy);
    asegurarEnvio();
  }
  soltar(ev) {
    if (ev.pointerId !== this.id) return;
    this.id = null;
    this.x = this.y = 0;
    this.e.classList.remove("activo");
    this.perilla.style.transform = "";
    asegurarEnvio();
  }
}

const joyA = new Joystick($("#joy-a"));
const joyB = new Joystick($("#joy-b"));
let temporizador = null, enviando = false;

function asegurarEnvio() {
  if (temporizador) return;
  enviarJoystick();
  temporizador = setInterval(enviarJoystick, 50);
}

async function enviarJoystick() {
  const activos = joyA.activo || joyB.activo;
  const datos = modo === "punta"
    ? { modo, x: joyA.x, y: joyA.y }
    : { modo, hombro: joyA.y, codo: joyB.y };
  if (!activos) { clearInterval(temporizador); temporizador = null; }
  if (enviando && activos) return; // no apilar peticiones si la red va lenta
  enviando = true;
  try { await api("/api/joystick", datos); } catch { /* el servidor frena solo si no llegan órdenes */ }
  finally { enviando = false; }
}

// Solo el grupo de los joysticks: los demás grupos (vista, calibración) tienen sus propios botones
for (const b of document.querySelectorAll("#modo-joy button")) {
  b.addEventListener("click", () => {
    modo = b.dataset.modo;
    for (const o of document.querySelectorAll("#modo-joy button")) {
      o.classList.toggle("activo", o === b);
      o.setAttribute("aria-checked", o === b);
    }
    joyA.dosEjes = modo === "punta";
    joyA.e.classList.toggle("xy", joyA.dosEjes);
    joyA.e.querySelector(".nombre").textContent = joyA.dosEjes ? "Punta" : "Hombro";
    joyB.e.hidden = joyA.dosEjes;
  });
}

// ---------- Medidas y límites ----------

const CAMPOS = [
  ["Geometría", [
    ["altura_hombro", "Mesa → eje del hombro", "mm"],
    ["brazo_recto", "Pieza gris: eje del hombro → doblez", "mm"],
    ["brazo_inclinado", "Pieza gris: doblez → eje del codo", "mm"],
    ["brazo_angulo", "Pieza gris: inclinación del doblez", "°"],
    ["largo_antebrazo", "Eje del codo → eje de la muñeca (punta)", "mm"],
    ["grosor_brazo", "Grosor del brazo", "mm"],
    ["grosor_antebrazo", "Grosor del antebrazo", "mm"],
    ["caja_largo", "Caja azul: largo", "mm"],
    ["caja_ancho", "Caja azul: ancho", "mm"],
    ["base_alto", "Caja azul: alto", "mm"],
    ["hombro_atras_giro", "Eje del hombro detrás del eje de giro", "mm"],
    ["giro_centro_us", "Servo de giro: pulso en 0° (brazo hacia el extremo redondo)", "µs"],
    ["giro_us_por_grado", "Servo de giro: µs por grado (negativo = al revés)", "µs/°"],
    ["margen", "Margen de seguridad", "mm"],
  ]],
  ["Límites", [
    ["hombro.minimo", "Hombro mínimo", "°"],
    ["hombro.maximo", "Hombro máximo", "°"],
    ["codo.minimo", "Codo mínimo", "°"],
    ["codo.maximo", "Codo máximo", "°"],
    ["torreta.minimo", "Giro mínimo", "°"],
    ["torreta.maximo", "Giro máximo", "°"],
    ["lim_muneca.minimo", "Muñeca mínimo", "°"],
    ["lim_muneca.maximo", "Muñeca máximo", "°"],
    ["lim_giro_muneca.minimo", "Giro de muñeca mínimo", "°"],
    ["lim_giro_muneca.maximo", "Giro de muñeca máximo", "°"],
    ["lim_garra.minimo", "Garra mínimo (0 = cerrada)", "%"],
    ["lim_garra.maximo", "Garra máximo (100 = abierta)", "%"],
  ]],
  ["Velocidad", [
    ["hombro.vmax", "Hombro, velocidad", "°/s"],
    ["hombro.amax", "Hombro, aceleración", "°/s²"],
    ["codo.vmax", "Codo, velocidad", "°/s"],
    ["codo.amax", "Codo, aceleración", "°/s²"],
    ["torreta.vmax", "Giro, velocidad", "°/s"],
    ["torreta.amax", "Giro, aceleración", "°/s²"],
    ["lim_muneca.vmax", "Muñeca, velocidad", "°/s"],
    ["lim_muneca.amax", "Muñeca, aceleración", "°/s²"],
    ["lim_giro_muneca.vmax", "Giro de muñeca, velocidad", "°/s"],
    ["lim_giro_muneca.amax", "Giro de muñeca, aceleración", "°/s²"],
    ["lim_garra.vmax", "Garra, velocidad", "%/s"],
    ["lim_garra.amax", "Garra, aceleración", "%/s²"],
  ]],
  ["Garra", [
    ["garra_montada", "Garra montada (cuenta en los choques)", ""],
    ["mano_base", "Pasador de la muñeca → frente de la U", "mm"],
    ["mano_palma", "Pasador → frente de la mano", "mm"],
    ["mano_largo", "Pasador → punta de los dedos", "mm"],
    ["mano_radio", "Grosor de la mano (radio, con su servo)", "mm"],
    ["garra_ancho_cerrada", "Mitad del ancho de los dedos, cerrada", "mm"],
    ["garra_ancho_abierta", "Mitad del ancho de los dedos, abierta", "mm"],
    ["garra_apertura", "Apertura entre las puntas, abierta", "mm"],
  ]],
  ["Reposo", [
    ["reposo_hombro", "Hombro en reposo", "°"],
    ["reposo_codo", "Codo en reposo", "°"],
  ]],
];

const leerCampo = (obj, ruta) => ruta.split(".").reduce((o, k) => o[k], obj);

function llenarMedidas() {
  const cont = $("#campos");
  cont.replaceChildren();
  for (const [titulo, campos] of CAMPOS) {
    const h = document.createElement("p");
    h.className = "grupo";
    h.textContent = titulo;
    cont.appendChild(h);
    const rejilla = document.createElement("div");
    rejilla.className = "campos";
    for (const [ruta, nombre, unidad] of campos) {
      const etiqueta = document.createElement("label");
      etiqueta.htmlFor = "c-" + ruta;
      etiqueta.innerHTML = `${nombre} <small>${unidad}</small>`;
      const entrada = document.createElement("input");
      entrada.id = "c-" + ruta;
      entrada.dataset.ruta = ruta;
      const valor = leerCampo(cfg, ruta);
      if (typeof valor === "boolean") {
        entrada.type = "checkbox";
        entrada.checked = valor;
      } else {
        entrada.type = "number";
        entrada.step = "any";
        entrada.inputMode = "decimal";
        entrada.value = valor;
      }
      rejilla.append(etiqueta, entrada);
    }
    cont.appendChild(rejilla);
  }
}

$("#form-medidas").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const datos = {};
  for (const entrada of document.querySelectorAll("#campos input")) {
    const [a, b] = entrada.dataset.ruta.split(".");
    const valor = entrada.type === "checkbox" ? entrada.checked : entrada.value;
    if (b) (datos[a] ??= {})[b] = valor;
    else datos[a] = valor;
  }
  const info = $("#info-medidas");
  try {
    await api("/api/config", datos, "PUT");
    info.textContent = "Guardado.";
    info.className = "info";
  } catch (e) {
    info.textContent = (e.datos && e.datos.errores ? e.datos.errores.join(" · ") : e.message);
    info.className = "info malo";
  }
});

$("#btn-reposo-aqui").addEventListener("click", async () => {
  await api("/api/reposo_aqui");
  $("#info-medidas").textContent = "Reposo actualizado con la pose actual.";
});

// ---------- Calibración del brazo real ----------

const CAL_AYUDA = {
  hombros: "Los dos hombros se mueven juntos, espejados alrededor de 1472 µs: los botones fijan el izquierdo y el derecho va al revés. Apoya el celular en la cara plana del tramo recto gris. Registra 3 puntos: algo adelante, vertical y algo atrás.",
  codo: "Pon los hombros en vertical (con «Hombros» o con «Sostener hombros en 90°»). Apoya el celular en el antebrazo amarillo. Registra 3 puntos: horizontal, algo arriba y algo abajo.",
};
// Lo que se registra y se muestra: el hombro izquierdo (el derecho es su espejo) o el codo
const INDICE = { hombros: 0, codo: 2 };
const SERVO_CAL = { hombros: "hombro_izq", codo: "codo" };
let calServo = "hombros";
let calSentido = 1;
let calUs = { hombros: 1472, codo: 1472 };
let ultimoToque = 0; // mientras se pulsa, manda el valor pedido y no el informado (que va atrasado)
let fisico = null;
let calibracion = null;
let sondeo = null;

const angServo = (us) => fmt((us - 1472) / 10.31, 0);

function anguloMedido() {
  const x = parseFloat($("#cal-medida").value.replace(",", "."));
  if (!Number.isFinite(x)) return null;
  // Hombro: 0 = horizontal adelante, 90 = vertical, más de 90 = hacia atrás.
  // Codo: inclinación del antebrazo menos la del tramo recto (hombros en 90°).
  if (calServo === "codo") return calSentido * x - 90;
  return calSentido > 0 ? x : 180 - x;
}

function pintarCalibracion() {
  for (const b of document.querySelectorAll("#cal-servos button")) b.classList.toggle("activo", b.dataset.servo === calServo);
  const esCodo = calServo === "codo";
  const [s1, s2] = document.querySelectorAll("#cal-sentido button");
  s1.textContent = esCodo ? "Punta arriba" : "Adelante";
  s2.textContent = esCodo ? "Punta abajo" : "Atrás";
  s1.classList.toggle("activo", calSentido > 0);
  s2.classList.toggle("activo", calSentido < 0);
  $("#cal-ayuda").textContent = CAL_AYUDA[calServo];

  const estado = $("#cal-estado");
  const conNano = fisico && !fisico.sin_nano;
  if (!fisico) estado.textContent = "Consultando…";
  else if (fisico.sin_nano) estado.textContent = "Sin Nano: cierra el simulador y ábrelo con «python3 servidor.py --nano».";
  else if (fisico.error) estado.textContent = fisico.error;
  else if (!fisico.conectado) estado.textContent = "Buscando el Nano… ¿está enchufado?";
  else if (!fisico.responde) estado.textContent = `Nano en ${fisico.puerto}, esperando al firmware…`;
  else estado.textContent = `Nano en ${fisico.puerto}` + (fisico.firmware ? ` · firmware ${fisico.firmware}` : "");
  estado.className = conNano && fisico.responde ? "info" : "info malo";

  const s = conNano && fisico.servos ? fisico.servos[INDICE[calServo]] : null;
  if (s && s.us !== null && Date.now() - ultimoToque > 1000) calUs[calServo] = s.us;
  $("#cal-us").textContent = calServo === "hombros"
    ? `${calUs.hombros} / ${2944 - calUs.hombros} µs` : `${calUs.codo} µs`;
  const activo = $("#cal-activo");
  activo.textContent = s && s.activo ? `activo · ≈ ${angServo(calUs[calServo])}° de servo` : "suelto";
  activo.className = s && s.activo ? "activo" : "";
  for (const b of document.querySelectorAll(".pasos button, #cal-activar, #cal-soltar, #cal-lim-min, #cal-lim-max")) {
    b.disabled = !(conNano && fisico.responde);
  }

  const ang = anguloMedido();
  $("#cal-resultado").textContent = ang === null ? "" :
    (calServo === "codo" ? `= codo ${fmt(ang)}° (supone los hombros en 90°)` : `= hombro ${fmt(ang)}°`);
  $("#cal-registrar").disabled = !(s && s.activo) || ang === null;
  $("#cal-dibujo").disabled = !(s && s.activo) || !estado;
  if (estado) {
    $("#cal-dibujo").textContent = `Registrar con el ángulo del dibujo (${fmt(calServo === "hombros" ? estado.hombro : estado.codo)}°)`;
  }

  if (!calibracion) return;
  const datos = calibracion[SERVO_CAL[calServo]];
  const [lmin, lmax] = datos.limites;
  const texto = (v) => (v === null ? "—" : calServo === "hombros" ? `${Math.round(v)} (der ${2944 - Math.round(v)})` : `${Math.round(v)}`);
  $("#cal-limites").textContent = `mín ${texto(lmin)} · máx ${texto(lmax)} µs`;
  $("#cal-lim-borrar").hidden = lmin === null && lmax === null;
  const lista = $("#cal-puntos");
  lista.replaceChildren();
  datos.puntos.forEach(([us, a], i) => {
    const li = document.createElement("li");
    li.textContent = `${Math.round(us)} µs → ${fmt(a)}°`;
    const b = document.createElement("button");
    b.textContent = "×";
    b.title = "Borrar este punto";
    b.onclick = async () => { calibracion = await api("/api/calibracion/borrar", { servo: SERVO_CAL[calServo], indice: i }); pintarCalibracion(); };
    li.appendChild(b);
    lista.appendChild(li);
  });
  const aj = datos.ajuste;
  const ajuste = $("#cal-ajuste");
  if (!aj) {
    ajuste.textContent = `Faltan puntos: mínimo 2, ideal 3 (${datos.puntos.length} registrados).`;
  } else {
    const ref = calServo === "codo" ? -90 : 90;
    ajuste.textContent = (aj.espejo ? "Espejo del izquierdo · " : "") +
      `${fmt(aj.pendiente, 3)} °/µs · ${ref}° en ${Math.round((ref - aj.corte) / aj.pendiente)} µs · error máx ${fmt(aj.error_max)}°`;
  }
  const hombrosListos = calibracion.hombro_izq.ajuste && calibracion.hombro_der.ajuste;
  $("#cal-sostener").disabled = !(hombrosListos && conNano && fisico.responde);
  const ini = conNano ? fisico.inicio : null;
  $("#cal-inicio").textContent = !conNano ? "—"
    : ini ? `hombros ${ini[0]}/${ini[1]} · codo ${ini[2]} µs` + (fisico.yendo_a_inicio ? " · yendo…" : "")
    : "sin guardar (arranca sin señal)";
  $("#cal-inicio-guardar").disabled = !(conNano && fisico.responde);
  $("#cal-inicio-ir").disabled = !(ini && fisico.responde);
}

async function sondearFisico() {
  try { fisico = await api("/api/fisico", undefined, "GET"); } catch { fisico = null; }
  pintarCalibracion();
}

async function calOrden(ruta, datos) {
  try { fisico = await api(ruta, datos); }
  catch (e) { $("#cal-estado").textContent = e.message; $("#cal-estado").className = "info malo"; return; }
  pintarCalibracion();
}

$("#panel-cal").addEventListener("toggle", async (ev) => {
  if (ev.target.open) {
    calibracion = await api("/api/calibracion", undefined, "GET").catch(() => null);
    sondearFisico();
    sondeo = setInterval(sondearFisico, 300);
  } else {
    clearInterval(sondeo);
  }
});

for (const b of document.querySelectorAll("#cal-servos button")) {
  b.addEventListener("click", () => { calServo = b.dataset.servo; calSentido = 1; pintarCalibracion(); });
}
for (const b of document.querySelectorAll("#cal-sentido button")) {
  b.addEventListener("click", () => { calSentido = b.dataset.sentido === "1" ? 1 : -1; pintarCalibracion(); });
}
for (const b of document.querySelectorAll(".pasos button")) {
  b.addEventListener("click", () => {
    let us = Math.min(2300, Math.max(700, calUs[calServo] + Number(b.dataset.paso)));
    const [lmin, lmax] = calibracion ? calibracion[SERVO_CAL[calServo]].limites : [null, null];
    if (lmin !== null) us = Math.max(us, lmin);
    if (lmax !== null) us = Math.min(us, lmax);
    calUs[calServo] = us;
    ultimoToque = Date.now();
    moverCal();
  });
}
const moverCal = () => calOrden(calServo === "hombros" ? "/api/hombros" : "/api/codo", { us: calUs[calServo] });
$("#cal-activar").addEventListener("click", moverCal);
$("#cal-soltar").addEventListener("click", () => calOrden("/api/soltar", {}));
$("#cal-sostener").addEventListener("click", () => calOrden("/api/calibracion/sostener", { angulo: 90 }));
$("#cal-inicio-guardar").addEventListener("click", () => calOrden("/api/inicio/guardar", {}));
$("#cal-inicio-ir").addEventListener("click", () => calOrden("/api/inicio/ir", {}));
$("#cal-medida").addEventListener("input", pintarCalibracion);

$("#cal-dibujo").addEventListener("click", async () => {
  const s = fisico.servos[INDICE[calServo]];
  const angulo = calServo === "hombros" ? estado.hombro : estado.codo;
  try { calibracion = await api("/api/calibracion/punto", { servo: SERVO_CAL[calServo], us: s.us, angulo }); }
  catch (e) { $("#cal-resultado").textContent = e.message; return; }
  pintarCalibracion();
});

async function fijarLimite(extremo, us) {
  try { calibracion = await api("/api/calibracion/limite", { servo: SERVO_CAL[calServo], extremo, us }); }
  catch (e) { $("#cal-estado").textContent = e.message; $("#cal-estado").className = "info malo"; return; }
  pintarCalibracion();
}
const pulsoActual = () => fisico.servos[INDICE[calServo]].us;
$("#cal-lim-min").addEventListener("click", () => fijarLimite("min", pulsoActual()));
$("#cal-lim-max").addEventListener("click", () => fijarLimite("max", pulsoActual()));
$("#cal-lim-borrar").addEventListener("click", async () => { await fijarLimite("min", null); await fijarLimite("max", null); });
$("#cal-registrar").addEventListener("click", async () => {
  const s = fisico.servos[INDICE[calServo]];
  try {
    calibracion = await api("/api/calibracion/punto", { servo: SERVO_CAL[calServo], us: s.us, angulo: anguloMedido() });
    $("#cal-medida").value = "";
  } catch (e) { $("#cal-resultado").textContent = e.message; return; }
  pintarCalibracion();
});

// ---------- Inicio ----------

if (window.INICIAL) {
  // El servidor incrusta config y estado: se dibuja al instante, sin esperar a la red
  cfg = window.INICIAL.config;
  estado = window.INICIAL.estado;
  construirEscena();
  configurarDeslizadores();
  llenarMedidas();
  actualizar();
  conectar();
} else {
  (async () => {
    await cargarConfig();
    estado = await api("/api/estado", undefined, "GET");
    actualizar();
    conectar();
  })();
}
