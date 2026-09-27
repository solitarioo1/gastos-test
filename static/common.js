const $ = (id) => document.getElementById(id);
const NS_SVG = "http://www.w3.org/2000/svg";

// ---------- Formato ----------

function soles(centimos) {
  const negativo = centimos < 0;
  const texto = (Math.abs(centimos) / 100).toLocaleString("es-PE", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return (negativo ? "-S/ " : "S/ ") + texto;
}

function crear(etiqueta, clase, texto) {
  const el = document.createElement(etiqueta);
  if (clase) el.className = clase;
  if (texto !== undefined) el.textContent = texto;
  return el;
}

function icono(nombre, tam = 18) {
  const svg = document.createElementNS(NS_SVG, "svg");
  for (const [k, v] of Object.entries({
    class: "icono",
    width: tam,
    height: tam,
    fill: "none",
    stroke: "currentColor",
    "stroke-width": "1.8",
    "stroke-linecap": "round",
    "stroke-linejoin": "round",
    "aria-hidden": "true",
    focusable: "false",
  })) svg.setAttribute(k, v);
  const uso = document.createElementNS(NS_SVG, "use");
  uso.setAttribute("href", "#i-" + nombre);
  svg.append(uso);
  return svg;
}

// ---------- Fechas ----------

function hoyISO() {
  if (window.TG && window.TG.hoy) return window.TG.hoy;
  const d = new Date();
  return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
}

function fechaDe(iso) {
  const [a, m, d] = iso.split("-").map(Number);
  return new Date(a, m - 1, d);
}

function isoDe(fecha) {
  return fecha.getFullYear() + "-" + String(fecha.getMonth() + 1).padStart(2, "0") + "-" + String(fecha.getDate()).padStart(2, "0");
}

function isoHaceDias(n) {
  const f = fechaDe(hoyISO());
  f.setDate(f.getDate() - n);
  return isoDe(f);
}

function diasDesdeHoy(iso) {
  return Math.round((fechaDe(hoyISO()) - fechaDe(iso)) / 86400000);
}

function fechaRelativa(iso) {
  const diff = diasDesdeHoy(iso);
  if (diff === 0) return "Hoy";
  if (diff === 1) return "Ayer";
  return fechaDe(iso).toLocaleDateString("es-PE", { day: "numeric", month: "short" });
}

function partesMes(m) {
  const [anio, num] = m.split("-").map(Number);
  return { anio, num };
}

function nombreMes(m, conAnio) {
  const { anio, num } = partesMes(m);
  return new Date(anio, num - 1, 1).toLocaleDateString("es-PE", conAnio ? { month: "long", year: "numeric" } : { month: "long" });
}

function sumarMes(m, delta) {
  const { anio, num } = partesMes(m);
  const d = new Date(anio, num - 1 + delta, 1);
  return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0");
}

const cabeceraFecha = $("fecha-hoy");
if (cabeceraFecha) {
  cabeceraFecha.textContent = fechaDe(hoyISO()).toLocaleDateString("es-PE", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

// ---------- API ----------

async function api(url, opciones = {}) {
  const resp = await fetch(url, {
    ...opciones,
    headers: { "Content-Type": "application/json" },
    body: opciones.body ? JSON.stringify(opciones.body) : undefined,
  });
  if (resp.status === 401) {
    window.location.href = "/login";
    throw new Error("Tu sesión expiró");
  }
  const datos = resp.status === 204 ? null : await resp.json();
  if (!resp.ok) throw new Error((datos && datos.error) || "Algo salió mal. Inténtalo otra vez.");
  return datos;
}

// ---------- Avisos ----------

function aviso(mensaje, { accion, error = false, duracion } = {}) {
  const caja = $("avisos");
  if (!caja) return;
  const el = crear("div", "aviso" + (error ? " aviso-error" : ""));
  el.append(icono(error ? "alerta" : "check", 18), crear("span", "aviso-texto", mensaje));
  const cerrar = () => el.remove();
  if (accion) {
    const b = crear("button", "aviso-accion", accion.texto);
    b.type = "button";
    b.addEventListener("click", async () => {
      cerrar();
      try {
        await accion.fn();
      } catch (e) {
        aviso(e.message, { error: true });
      }
    });
    el.append(b);
  }
  caja.append(el);
  setTimeout(cerrar, duracion || (accion ? 9000 : 4500));
}

// Borra un movimiento y ofrece deshacerlo (lo vuelve a crear con los mismos datos).
async function borrarConDeshacer(tabla, mov, alTerminar) {
  if (!confirm(`¿Seguro que quieres borrar «${mov.concepto}» (${soles(mov.monto_centimos)})?`)) return;
  await api(`/api/${tabla}/${mov.id}`, { method: "DELETE" });
  aviso(`Borrado: ${mov.concepto}`, {
    accion: {
      texto: "Deshacer",
      fn: async () => {
        await api(`/api/${tabla}`, {
          method: "POST",
          body: { concepto: mov.concepto, monto: mov.monto_centimos / 100, fecha: mov.fecha, categoria: mov.categoria },
        });
        await alTerminar();
      },
    },
  });
  await alTerminar();
}

// ---------- Categorías (de fábrica + las del usuario) ----------

const SIN_CLASIFICAR = "Sin clasificar";
const NUEVA_CATEGORIA = "__nueva__";

const categoriasDe = (tipo) => (tipo === "ingreso" ? window.TG.categoriasIngreso : window.TG.categorias);
const categoriasElegibles = (tipo) => categoriasDe(tipo).filter((c) => c !== SIN_CLASIFICAR);

function registrarCategoriaLocal(tipo, nombre) {
  const lista = categoriasDe(tipo);
  if (lista.includes(nombre)) return;
  const i = lista.indexOf(SIN_CLASIFICAR);
  lista.splice(i === -1 ? lista.length : i, 0, nombre);
}

const dlgCategoria = $("dlg-categoria");
let categoriaPendiente = null; // { resolve, guardar, tipo }

// Abre el diálogo de categoría. `guardar({nombre, tipo})` hace el trabajo y, si lanza un error,
// el mensaje se muestra dentro del diálogo y sigue abierto. Devuelve el resultado, o null si se cancela.
function pedirCategoria({ tipo = null, actual = null, guardar }) {
  return new Promise((resolve) => {
    categoriaPendiente = { resolve, guardar, tipo: tipo || "gasto" };
    $("dlg-cat-titulo").textContent = actual ? "Cambiar nombre" : "Nueva categoría";
    $("dlg-cat-guardar").textContent = actual ? "Guardar" : "Crear categoría";
    $("dlg-cat-tipo-caja").hidden = Boolean(tipo);
    marcarTipoCategoria(categoriaPendiente.tipo);
    $("dlg-cat-nombre").value = actual || "";
    $("dlg-cat-error").hidden = true;
    dlgCategoria.showModal();
    $("dlg-cat-nombre").focus();
    $("dlg-cat-nombre").select();
  });
}

function marcarTipoCategoria(tipo) {
  categoriaPendiente.tipo = tipo;
  dlgCategoria.querySelectorAll("[role=radio]").forEach((b) => b.setAttribute("aria-checked", b.dataset.tipo === tipo ? "true" : "false"));
}

function cerrarDialogoCategoria(resultado) {
  if (!categoriaPendiente) return;
  const { resolve } = categoriaPendiente;
  categoriaPendiente = null;
  if (dlgCategoria.open) dlgCategoria.close();
  resolve(resultado);
}

if (dlgCategoria) {
  dlgCategoria.querySelectorAll("[role=radio]").forEach((b) => b.addEventListener("click", () => marcarTipoCategoria(b.dataset.tipo)));
  $("dlg-cat-cancelar").addEventListener("click", () => cerrarDialogoCategoria(null));
  $("dlg-cat-cerrar").addEventListener("click", () => cerrarDialogoCategoria(null));
  dlgCategoria.addEventListener("cancel", (ev) => {
    ev.preventDefault();
    cerrarDialogoCategoria(null);
  });
  dlgCategoria.addEventListener("click", (ev) => {
    if (ev.target === dlgCategoria) cerrarDialogoCategoria(null);
  });
  $("form-categoria").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (!categoriaPendiente) return;
    const nombre = $("dlg-cat-nombre").value.trim();
    const error = $("dlg-cat-error");
    if (!nombre) {
      error.textContent = "Escribe un nombre para la categoría.";
      error.hidden = false;
      return;
    }
    try {
      const resultado = await categoriaPendiente.guardar({ nombre, tipo: categoriaPendiente.tipo });
      cerrarDialogoCategoria(resultado);
    } catch (e) {
      error.textContent = e.message;
      error.hidden = false;
    }
  });
}

// Crea una categoría propia desde cualquier pantalla y la deja lista para usar.
function crearCategoriaInteractivo(tipo) {
  return pedirCategoria({
    tipo,
    guardar: async ({ nombre, tipo: t }) => {
      const c = await api("/api/categorias", { method: "POST", body: { nombre, tipo: t } });
      registrarCategoriaLocal(t, c.nombre);
      aviso(`Categoría «${c.nombre}» creada.`);
      return { ...c, tipo: t };
    },
  });
}

function llenarSelectCategoria(select, tipo, { valor, automatica = false, agrupado = false, sinClasificar = true, nueva = true } = {}) {
  select.replaceChildren();
  if (automatica) select.append(new Option("Automática (yo la adivino)", ""));
  const grupo = (etiqueta, t) => {
    const g = document.createElement("optgroup");
    g.label = etiqueta;
    categoriasElegibles(t).forEach((c) => g.append(new Option(c, c)));
    return g;
  };
  if (agrupado) {
    select.append(grupo("Gastos", "gasto"), grupo("Ingresos", "ingreso"));
  } else {
    categoriasDe(tipo).filter((c) => sinClasificar || c !== SIN_CLASIFICAR).forEach((c) => select.append(new Option(c, c)));
  }
  if (nueva) select.append(new Option("＋ Nueva categoría…", NUEVA_CATEGORIA));
  if (valor !== undefined) select.value = valor;
}

// `tipo` puede ser "gasto", "ingreso", null (se pregunta al crear) o una función que lo devuelve.
function prepararSelectCategoria(select, tipo, opciones = {}) {
  const tipoActual = () => (typeof tipo === "function" ? tipo() : tipo);
  const rellenar = (valor) => llenarSelectCategoria(select, tipoActual(), { ...opciones, valor });
  rellenar(opciones.valor);
  let anterior = select.value;
  select.addEventListener("change", async () => {
    if (select.value !== NUEVA_CATEGORIA) {
      anterior = select.value;
      return;
    }
    const c = await crearCategoriaInteractivo(tipoActual());
    if (c) {
      rellenar(c.nombre);
      anterior = c.nombre;
    } else {
      select.value = anterior;
    }
  });
  return rellenar;
}

// ---------- Tema claro / oscuro ----------

const botonTema = $("cambiar-tema");
if (botonTema) {
  botonTema.addEventListener("click", () => {
    const raiz = document.documentElement;
    const nuevo = raiz.getAttribute("data-bs-theme") === "dark" ? "light" : "dark";
    raiz.setAttribute("data-bs-theme", nuevo);
    try {
      localStorage.setItem("tema", nuevo);
    } catch (e) {}
  });
}

// ---------- Menú del celular: hoja que se desliza (no un acordeón que empuja el contenido) ----------

const botonMenuMovil = $("btn-menu-movil");
if (botonMenuMovil) {
  const fondoMenuMovil = $("fondo-menu-movil");
  const cerrarMenuMovil = () => {
    document.body.classList.remove("menu-movil-abierto");
    botonMenuMovil.setAttribute("aria-expanded", "false");
  };
  botonMenuMovil.addEventListener("click", () => {
    const abierto = document.body.classList.toggle("menu-movil-abierto");
    botonMenuMovil.setAttribute("aria-expanded", abierto ? "true" : "false");
  });
  fondoMenuMovil.addEventListener("click", cerrarMenuMovil);
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") cerrarMenuMovil();
  });
  document.querySelectorAll("#menu-lateral .nav-link").forEach((a) => a.addEventListener("click", cerrarMenuMovil));
}

// ---------- Instalación como app (PWA) ----------

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}
