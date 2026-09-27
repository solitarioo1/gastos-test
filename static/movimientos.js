const raiz = $("movimientos");
const MES_ACTUAL = raiz.dataset.mesActual;

// Se puede llegar con filtros en la dirección (ej.: desde el aviso de "sin clasificar").
const parametros = new URLSearchParams(location.search);
const mesPedido = parametros.get("mes") || "";
const estado = {
  tipo: parametros.get("tipo") === "ingresos" ? "ingresos" : "gastos",
  mes: /^\d{4}-(0[1-9]|1[0-2])$/.test(mesPedido) && mesPedido <= MES_ACTUAL ? mesPedido : MES_ACTUAL,
  q: "",
  categoria: parametros.get("categoria") || "",
};
let editando = null; // movimiento que se edita; null = agregar uno nuevo
let temporizador = null;

const dialogo = $("dialogo");
const formMov = $("form-mov");

const tipoCategoria = () => (estado.tipo === "gastos" ? "gasto" : "ingreso");
const listaCategorias = () => categoriasDe(tipoCategoria());
const singular = () => tipoCategoria();
const rellenarCategoriaDialogo = prepararSelectCategoria($("f-categoria"), tipoCategoria);
document.querySelectorAll(".segmentado [role=tab]").forEach((o) => o.setAttribute("aria-selected", o.dataset.tipo === estado.tipo ? "true" : "false"));

// ---------- Cabecera ----------

function pintarResumen(r) {
  const esGasto = estado.tipo === "gastos";
  $("res-etiqueta").textContent = `${esGasto ? "Gastado" : "Ingresado"} en ${nombreMes(r.mes, true)}`;
  $("res-total").textContent = soles(r.total_centimos);
  $("res-n").textContent = r.n;
  $("res-mayor-etiqueta").textContent = esGasto ? "Categoría que más pesa" : "Ingreso principal";
  $("res-mayor").textContent = r.mayor_categoria || "—";

  const anterior = nombreMes(r.mes_anterior, false);
  let texto = "";
  if (r.total_centimos > 0 && r.total_mes_anterior_centimos > 0) {
    const diff = r.total_centimos - r.total_mes_anterior_centimos;
    texto =
      diff === 0
        ? `Igual que en ${anterior}`
        : `${soles(Math.abs(diff))} ${diff > 0 ? "más" : "menos"} que en ${anterior}` + (r.mes === MES_ACTUAL ? " (mes completo)" : "");
  }
  $("res-comparacion").textContent = texto;
}

function pintarFiltros() {
  $("mes-etiqueta").textContent = nombreMes(estado.mes, true);
  $("mes-siguiente").disabled = estado.mes >= MES_ACTUAL;
  const sel = $("filtro-categoria");
  const actual = estado.categoria;
  sel.replaceChildren(new Option("Todas las categorías", ""));
  listaCategorias().forEach((c) => sel.append(new Option(c, c)));
  sel.value = actual;
}

// ---------- Lista ----------

function etiquetaDia(fecha) {
  const base = fechaDe(fecha).toLocaleDateString("es-PE", { weekday: "short", day: "numeric", month: "short" });
  const diff = diasDesdeHoy(fecha);
  return diff === 0 ? "Hoy · " + base : diff === 1 ? "Ayer · " + base : base;
}

function filaMovimiento(m) {
  const esIngreso = estado.tipo === "ingresos";
  const fila = crear("div", "mov");

  const principal = crear("button", "mov-principal");
  principal.type = "button";
  principal.setAttribute("aria-label", `Editar ${m.concepto}`);
  principal.append(
    crear("span", "mov-concepto", m.concepto),
    crear("span", "chip" + (m.categoria === SIN_CLASIFICAR ? " chip-pendiente" : ""), m.categoria)
  );
  principal.addEventListener("click", () => abrirDialogo(m));

  const monto = crear("div", "monto" + (esIngreso ? " monto-ingreso" : ""), (esIngreso ? "+" : "") + soles(m.monto_centimos));

  const acciones = crear("div", "mov-acciones");
  const editar = crear("button", "btn btn-icon btn-sm btn-ghost-secondary");
  editar.type = "button";
  editar.setAttribute("aria-label", `Editar ${m.concepto}`);
  editar.append(icono("editar", 16));
  editar.addEventListener("click", () => abrirDialogo(m));
  const borrar = crear("button", "btn btn-icon btn-sm btn-ghost-danger");
  borrar.type = "button";
  borrar.setAttribute("aria-label", `Borrar ${m.concepto}`);
  borrar.append(icono("borrar", 16));
  borrar.addEventListener("click", async () => {
    try {
      await borrarConDeshacer(estado.tipo, m, cargar);
    } catch (e) {
      aviso(e.message, { error: true });
    }
  });
  acciones.append(editar, borrar);

  fila.append(principal, monto, acciones);
  return fila;
}

function pintarLista(items) {
  const lista = $("lista");
  lista.replaceChildren();
  const hayFiltro = estado.q || estado.categoria;
  $("vacio").hidden = items.length > 0;
  if (!items.length) {
    $("vacio-titulo").textContent = hayFiltro
      ? "No encontré nada con ese filtro"
      : `No hay ${estado.tipo} en ${nombreMes(estado.mes, true)}`;
    $("vacio-detalle").textContent = hayFiltro
      ? "Prueba con otra palabra o quita el filtro."
      : "Cuando anotes uno en Inicio, aparecerá aquí.";
    return;
  }

  let dia = null;
  let totalDia = 0;
  let cabecera = null;
  const cerrarDia = () => {
    if (cabecera) cabecera.querySelector(".dia-total").textContent = soles(totalDia);
  };
  for (const m of items) {
    if (m.fecha !== dia) {
      cerrarDia();
      dia = m.fecha;
      totalDia = 0;
      cabecera = crear("div", "dia-cabecera");
      cabecera.append(crear("span", "", etiquetaDia(dia)), crear("span", "dia-total"));
      lista.append(cabecera);
    }
    totalDia += m.monto_centimos;
    lista.append(filaMovimiento(m));
  }
  cerrarDia();
}

async function cargar() {
  const params = new URLSearchParams({ tipo: estado.tipo, mes: estado.mes });
  if (estado.q) params.set("q", estado.q);
  if (estado.categoria) params.set("categoria", estado.categoria);
  try {
    const r = await api("/api/movimientos?" + params);
    pintarResumen(r.resumen);
    pintarLista(r.items);
  } catch (e) {
    aviso(e.message, { error: true });
  }
}

// ---------- Diálogo de agregar / editar ----------

function abrirDialogo(mov) {
  editando = mov || null;
  $("dialogo-titulo").textContent = mov ? `Editar ${singular()}` : `Agregar ${singular()}`;
  $("f-error").hidden = true;
  $("f-borrar").hidden = !mov;

  const hoy = hoyISO();
  $("f-fecha").max = hoy;
  if (mov) {
    $("f-concepto").value = mov.concepto;
    $("f-monto").value = (mov.monto_centimos / 100).toFixed(2);
    $("f-fecha").value = mov.fecha;
    rellenarCategoriaDialogo(mov.categoria);
  } else {
    formMov.reset();
    $("f-fecha").value = estado.mes === MES_ACTUAL ? hoy : estado.mes + "-01";
    rellenarCategoriaDialogo(SIN_CLASIFICAR); // al guardar así, la app la adivina
  }
  dialogo.showModal();
  $("f-concepto").focus();
}

function cerrarDialogo() {
  dialogo.close();
}

formMov.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const cuerpo = {
    concepto: $("f-concepto").value.trim(),
    monto: $("f-monto").value,
    fecha: $("f-fecha").value,
    categoria: $("f-categoria").value,
  };
  const error = $("f-error");
  if (!cuerpo.concepto || !(parseFloat(cuerpo.monto) > 0) || !cuerpo.fecha) {
    error.textContent = "Completa el concepto, un monto mayor a cero y la fecha.";
    error.hidden = false;
    return;
  }
  try {
    if (editando) {
      await api(`/api/${estado.tipo}/${editando.id}`, { method: "PATCH", body: cuerpo });
    } else {
      await api(`/api/${estado.tipo}`, { method: "POST", body: cuerpo });
    }
    cerrarDialogo();
    const cambioCategoria = cuerpo.categoria !== SIN_CLASIFICAR && (!editando || cuerpo.categoria !== editando.categoria);
    aviso(
      cambioCategoria
        ? `Guardado. Desde ahora «${cuerpo.concepto}» va en ${cuerpo.categoria}.`
        : editando
        ? "Cambios guardados."
        : `${singular()[0].toUpperCase() + singular().slice(1)} agregado.`
    );
    // si la fecha cae en otro mes, sigue al movimiento para que se vea que se guardó
    const mesNuevo = cuerpo.fecha.slice(0, 7);
    if (mesNuevo !== estado.mes) estado.mes = mesNuevo;
    pintarFiltros();
    await cargar();
  } catch (e) {
    error.textContent = e.message;
    error.hidden = false;
  }
});

$("f-borrar").addEventListener("click", async () => {
  const mov = editando;
  cerrarDialogo();
  try {
    await borrarConDeshacer(estado.tipo, mov, cargar);
  } catch (e) {
    aviso(e.message, { error: true });
  }
});
$("f-cancelar").addEventListener("click", cerrarDialogo);
$("f-cerrar").addEventListener("click", cerrarDialogo);
dialogo.addEventListener("click", (ev) => {
  if (ev.target === dialogo) cerrarDialogo();
});
$("agregar").addEventListener("click", () => abrirDialogo(null));

// ---------- Controles ----------

document.querySelectorAll(".segmentado [role=tab]").forEach((b) =>
  b.addEventListener("click", () => {
    if (estado.tipo === b.dataset.tipo) return;
    estado.tipo = b.dataset.tipo;
    estado.categoria = "";
    document.querySelectorAll(".segmentado [role=tab]").forEach((o) => o.setAttribute("aria-selected", o === b ? "true" : "false"));
    pintarFiltros();
    cargar();
  })
);

$("mes-anterior").addEventListener("click", () => {
  estado.mes = sumarMes(estado.mes, -1);
  pintarFiltros();
  cargar();
});
$("mes-siguiente").addEventListener("click", () => {
  if (estado.mes < MES_ACTUAL) {
    estado.mes = sumarMes(estado.mes, 1);
    pintarFiltros();
    cargar();
  }
});
$("filtro-categoria").addEventListener("change", (ev) => {
  estado.categoria = ev.target.value;
  cargar();
});
$("buscar").addEventListener("input", (ev) => {
  clearTimeout(temporizador);
  temporizador = setTimeout(() => {
    estado.q = ev.target.value.trim();
    cargar();
  }, 250);
});

pintarFiltros();
cargar();

// Llegar con ?agregar=1 (ej.: botón "Anotar ingreso" de Registros) abre el diálogo directo.
if (parametros.get("agregar") === "1") {
  history.replaceState(null, "", location.pathname + location.search.replace(/[?&]agregar=1/, "").replace(/^&/, "?"));
  abrirDialogo(null);
}
