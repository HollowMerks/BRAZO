// Vista 3D del brazo con las piezas del modelo que imprimió el usuario.
// Solo dibuja lo que manda el servidor: la pose, los límites y los choques se
// calculan allí (motor/), igual que para la vista lateral.
import * as THREE from "three";
import { OrbitControls } from "./vendor/OrbitControls.js";
import { toCreasedNormals } from "./vendor/BufferGeometryUtils.js";

// Los colores del brazo real: caja celeste, torreta y antebrazo amarillos, brazo gris
const COLOR = { caja: 0x27b4d6, torreta: 0xf2c414, brazo: 0xa7acb1, antebrazo: 0xf2c414, servo: 0x2e323a,
  mano: 0xa7acb1, dedos: 0x6b7280, engranaje: 0xc9a227 };
const OBJETIVO = 0x5cc8ff, MALO = 0xff5d5d, REAL = 0xff9f43;
const rad = (g) => (g * Math.PI) / 180;

// Malla de herramientas/exportar_modelo.py: "BRZ1", vértices, triángulos, posiciones, índices
export function leerMalla(buffer) {
  const dv = new DataView(buffer);
  const magia = String.fromCharCode(...new Uint8Array(buffer, 0, 4));
  if (magia !== "BRZ1") throw new Error("formato de malla desconocido");
  const nv = dv.getUint32(4, true), nt = dv.getUint32(8, true);
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(buffer, 12, nv * 3), 3));
  g.setIndex(new THREE.BufferAttribute(new Uint32Array(buffer, 12 + nv * 12, nt * 3), 1));
  // Aristas vivas donde la pieza las tiene, superficies curvas suaves
  return toCreasedNormals(g, rad(30));
}

// Las piezas encadenadas como en el brazo: caja fija → torreta (giro) → brazo (hombro) → antebrazo (codo)
export class Brazo {
  constructor(mallas, medidas) {
    const material = (color) => new THREE.MeshStandardMaterial({ color, roughness: 0.72, metalness: 0.05 });
    this.medidas = medidas;
    this.moviles = [material(COLOR.brazo), material(COLOR.antebrazo)];
    this.raiz = new THREE.Group();
    this.torreta = new THREE.Group();
    this.hombro = new THREE.Group();
    this.codo = new THREE.Group();
    // Marco del dibujo lateral (x desde el eje del hombro, y desde la mesa) para las líneas guía
    this.plano = new THREE.Group();
    this.raiz.add(new THREE.Mesh(mallas.caja, material(COLOR.caja)), this.torreta);
    this.torreta.add(new THREE.Mesh(mallas.torreta, material(COLOR.torreta)), this.hombro, this.plano);
    this.brazo = new THREE.Mesh(mallas.brazo, this.moviles[0]);
    this.brazoOriginal = mallas.brazo.attributes.position.array.slice();
    this.recorte = 0;
    this.hombro.add(this.brazo, this.codo);
    this.codo.add(new THREE.Mesh(mallas.antebrazo, this.moviles[1]));
    if (mallas.muneca && medidas.mano) this.armarMano(mallas, medidas.mano, material);
    // Los dos MG995 de los hombros: la pestaña atornillada por fuera de cada pared,
    // el cuerpo cruzando la ventana y el eje hacia el brazo
    const s = medidas.servo_hombro;
    const negro = material(COLOR.servo);
    for (const lado of [1, -1]) {
      const cuerpo = new THREE.Mesh(new THREE.BoxGeometry(40.7, 19.7, 37), negro);
      cuerpo.position.set(s.x, s.y, lado * (s.pared[1] + 26.5 - 18.5));
      const pestana = new THREE.Mesh(new THREE.BoxGeometry(54, 19.7, 2.5), negro);
      pestana.position.set(s.x, s.y, lado * (s.pared[1] + 1.25));
      this.torreta.add(cuerpo, pestana);
    }
  }

  // Garra: muñeca (pasador en la punta del antebrazo) → mano (giro sobre su eje) → dedos.
  // Los dedos forman un paralelogramo: engranaje y eslabón giran lo mismo y el dedo se traslada
  armarMano(mallas, m, material) {
    const mat = (color) => { const x = material(color); this.moviles.push(x); return x; };
    const caja = (padre, mat, [x, y, z], [w, h, d]) => {
      const b = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
      b.position.set(x, y, z);
      padre.add(b);
    };
    const servo = mat(COLOR.servo), mano = mat(COLOR.mano), dedos = mat(COLOR.dedos);
    this.muneca = new THREE.Group();
    this.codo.add(this.muneca);
    this.muneca.add(new THREE.Mesh(mallas.muneca, mat(COLOR.antebrazo)));
    // MG90S de la muñeca, por fuera de un brazo de la U y a lo largo del antebrazo (ubicación aproximada)
    caja(this.muneca, servo, [-5.3, 0, 29.75], [22.5, 12.2, 16.5]);
    caja(this.muneca, servo, [-5.3, 0, 22.75], [32.2, 12.2, 2.5]);
    this.mano = new THREE.Group();
    this.mano.position.set(m.origen, 0, 0);
    this.muneca.add(this.mano);
    this.mano.add(new THREE.Mesh(mallas.mano_sup, mano), new THREE.Mesh(mallas.mano_inf, mano));
    // MG90S del giro de muñeca: entre las placas, atornillado a la pared de atrás, con su
    // brazo contra la U; y el de la garra, parado sobre la placa de arriba
    caja(this.mano, servo, [-20.45, 0, 5.3], [22.7, 12.2, 22.5]);
    caja(this.mano, servo, [-26.25, 0, 5.3], [2.5, 12.2, 32.2]);
    const disco = new THREE.Mesh(new THREE.CylinderGeometry(10, 10, 2, 24), servo);
    disco.rotation.z = Math.PI / 2;
    disco.position.set(-35, 0, 0);
    this.mano.add(disco);
    caja(this.mano, servo, [4, 13.55, 0], [12.2, 22.7, 22.5]);
    caja(this.mano, servo, [4, 10.25, 0], [12.2, 2.5, 32.2]);
    this.engranaje = new THREE.Mesh(mallas.engranaje, mat(COLOR.engranaje));
    this.engranaje.position.set(m.engranaje_servo[0], 0, -m.engranaje_servo[1]);
    this.mano.add(this.engranaje);
    this.dedos = [1, -1].map((lado) => {
      const pieza = (malla) => {
        const g = new THREE.Group();
        const malla3d = new THREE.Mesh(malla, dedos);
        if (lado < 0) malla3d.rotation.x = Math.PI; // la otra copia impresa, dada vuelta
        g.add(malla3d);
        this.mano.add(g);
        return g;
      };
      const d = { lado, engranaje: pieza(mallas.dedo_engranaje), eslabon: pieza(mallas.eslabon), dedo: pieza(mallas.dedo) };
      d.engranaje.position.set(m.engranaje[0], 0, -lado * m.engranaje[1]);
      d.eslabon.position.set(m.eslabon[0], 0, -lado * m.eslabon[1]);
      d.dedo.rotation.y = rad(m.dedo_angulo * lado);
      return d;
    });
    this.abrir(0);
  }

  // 0 = cerrada, 100 = abierta: el ángulo de los brazos va de m.cerrada a m.abierta
  abrir(porcentaje) {
    const m = this.medidas.mano;
    const t = rad(m.cerrada + (m.abierta - m.cerrada) * Math.min(Math.max(porcentaje, 0), 100) / 100);
    for (const d of this.dedos) {
      const a = d.lado * t;
      d.engranaje.rotation.y = a;
      d.eslabon.rotation.y = a;
      d.dedo.position.set(m.engranaje[0] + m.brazo * Math.cos(a), 0, -d.lado * m.engranaje[1] - m.brazo * Math.sin(a));
    }
    this.engranaje.rotation.y = -1.15 * (t - rad(m.cerrada));
  }

  // La pieza gris real se acortó cortando el tramo recto por la mitad: lo que queda
  // por encima del corte baja `recorte` mm y la franja cortada desaparece
  recortar(recorte) {
    const pos = this.brazo.geometry.attributes.position;
    const c = this.medidas.corte_brazo;
    const o = this.brazoOriginal;
    for (let i = 1; i < o.length; i += 3) {
      const y = o[i];
      pos.array[i] = y <= c ? y : y < c + recorte ? c : y - recorte;
    }
    pos.needsUpdate = true;
    this.brazo.geometry.computeBoundingSphere();
    this.recorte = recorte;
  }

  configurar(cfg) {
    const recorte = this.medidas.brazo_recto - cfg.brazo_recto;
    if (recorte !== this.recorte) this.recortar(recorte);
    const s = this.medidas.servo_hombro;
    // La torreta se apoya donde haga falta para que el eje de sus servos quede a la altura del hombro
    this.torreta.position.set(0, cfg.altura_hombro - s.y, 0);
    this.torreta.rotation.y = rad(cfg.giro);
    this.hombro.position.set(-cfg.hombro_atras_giro, s.y, 0);
    const a = rad(cfg.brazo_angulo);
    this.codo.position.set(cfg.brazo_inclinado * Math.sin(a), cfg.brazo_recto + cfg.brazo_inclinado * Math.cos(a), 0);
    this.plano.position.set(-cfg.hombro_atras_giro, -this.torreta.position.y, 0);
    if (this.muneca) {
      this.muneca.visible = cfg.garra_montada;
      this.muneca.position.set(cfg.largo_antebrazo, 0, 0);
    }
  }

  posar(hombro, codo, choque, giro, mano) {
    if (this.muneca && mano) {
      this.muneca.rotation.z = rad(mano.muneca);
      this.mano.rotation.x = rad(mano.giro_muneca);
      this.abrir(mano.garra);
    }
    this.torreta.rotation.y = rad(giro);
    // Ángulos mecánicos como en motor/cinematica.py: hombro 90 = tramo recto vertical,
    // antebrazo a (hombro + codo) grados de la horizontal
    this.hombro.rotation.z = rad(hombro - 90);
    this.codo.rotation.z = rad(codo + 90);
    for (const m of this.moviles) m.emissive.setHex(choque ? 0x5a0d0d : 0x000000);
  }
}

// Línea guía en el plano del brazo, siempre visible por encima de las piezas
class Guia {
  constructor(padre, color) {
    this.material = new THREE.LineBasicMaterial({ color, depthTest: false, transparent: true, opacity: 0.95 });
    this.linea = new THREE.Line(new THREE.BufferGeometry(), this.material);
    this.linea.renderOrder = 10;
    this.linea.frustumCulled = false;
    this.linea.visible = false;
    padre.add(this.linea);
  }
  poner(puntos, color) {
    this.linea.visible = Boolean(puntos && puntos.length > 1);
    if (!this.linea.visible) return;
    const pos = new Float32Array(puntos.length * 3);
    puntos.forEach(([x, y], i) => pos.set([x, y, 0], i * 3));
    this.linea.geometry.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    if (color !== undefined) this.material.color.setHex(color);
  }
}

class Vista {
  constructor(caja, brazo) {
    this.caja = caja;
    this.brazo = brazo;
    this.pendiente = false;
    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.setClearColor(0x0e1013);
    caja.replaceChildren(this.renderer.domElement);

    this.escena = new THREE.Scene();
    this.camara = new THREE.PerspectiveCamera(35, 1, 5, 6000);
    // De costado como la vista lateral (adelante = derecha), un poco desde arriba y de frente
    this.camara.position.set(330, 330, 600);
    this.controles = new OrbitControls(this.camara, this.renderer.domElement);
    this.controles.target.set(70, 150, 0);
    this.controles.maxPolarAngle = rad(88); // no meterse bajo la mesa
    this.controles.minDistance = 150;
    this.controles.maxDistance = 2500;
    this.controles.update();
    this.controles.addEventListener("change", () => this.dibujar());

    this.escena.add(new THREE.HemisphereLight(0xdfe7f2, 0x20242a, 1.4));
    const sol = new THREE.DirectionalLight(0xffffff, 2.4);
    sol.position.set(300, 650, 450);
    const relleno = new THREE.DirectionalLight(0xffffff, 0.7);
    relleno.position.set(-450, 200, -350);
    this.escena.add(sol, relleno);

    const mesa = new THREE.Mesh(new THREE.PlaneGeometry(2400, 2400), new THREE.MeshStandardMaterial({ color: 0x161a1f, roughness: 1 }));
    mesa.rotation.x = -Math.PI / 2;
    const rejilla = new THREE.GridHelper(2400, 48, 0x2b323c, 0x20262e); // cuadros de 50 mm
    rejilla.position.y = 0.3;
    this.escena.add(mesa, rejilla, brazo.raiz);

    this.fantasma = new Guia(brazo.plano, OBJETIVO);
    this.traza = new Guia(brazo.plano, OBJETIVO);
    this.real = new Guia(brazo.plano, REAL);

    new ResizeObserver(() => this.medir()).observe(caja);
    this.medir();
  }

  medir() {
    const w = this.caja.clientWidth, h = this.caja.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this.camara.aspect = w / h;
    this.camara.updateProjectionMatrix();
    this.dibujar();
  }

  configurar(cfg) {
    this.brazo.configurar(cfg);
    this.dibujar();
  }

  // estado: el del servidor; fantasma: {puntos, malo} de la pose pedida; traza y real: listas de [x, y]
  actualizar({ estado, fantasma, traza, real }) {
    this.brazo.posar(estado.hombro, estado.codo, estado.holgura < 0, estado.giro, estado.mano);
    this.fantasma.poner(fantasma && fantasma.puntos, fantasma && fantasma.malo ? MALO : OBJETIVO);
    this.traza.poner(traza);
    this.real.poner(real);
    this.dibujar();
  }

  dibujar() {
    // Un cuadro por refresco como mucho, y nada mientras la vista está oculta
    if (this.pendiente || !this.caja.offsetParent) return;
    this.pendiente = true;
    requestAnimationFrame(() => {
      this.pendiente = false;
      this.renderer.render(this.escena, this.camara);
    });
  }
}

async function arrancar() {
  const caja = document.getElementById("vista3d");
  try {
    const info = await (await fetch("modelo/piezas.json")).json();
    const buffers = await Promise.all(info.piezas.map(async (nombre) => {
      const r = await fetch(`modelo/${nombre}.bin`);
      if (!r.ok) throw new Error(`falta la pieza «${nombre}»`);
      return r.arrayBuffer();
    }));
    const mallas = Object.fromEntries(info.piezas.map((nombre, i) => [nombre, leerMalla(buffers[i])]));
    window.vista3d = new Vista(caja, new Brazo(mallas, info.medidas));
    window.dispatchEvent(new Event("vista3d-lista"));
  } catch (e) {
    window.vista3d = null;
    window.dispatchEvent(new CustomEvent("vista3d-error", { detail: e.message }));
  }
}

if (typeof document !== "undefined" && document.getElementById("vista3d")) arrancar();
