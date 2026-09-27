// ---------- Pestañas ----------

function mostrarPanel(nombre) {
  for (const b of document.querySelectorAll(".segmentado [role=tab]")) {
    b.setAttribute("aria-selected", b.dataset.panel === nombre ? "true" : "false");
  }
  for (const panel of ["topes", "fijos", "categorias"]) $("panel-" + panel).hidden = nombre !== panel;
  history.replaceState(null, "", nombre === "topes" ? location.pathname : "#" + nombre);
}
document.querySelectorAll(".segmentado [role=tab]").forEach((b) => b.addEventListener("click", () => mostrarPanel(b.dataset.panel)));
if (["#fijos", "#categorias"].includes(location.hash)) mostrarPanel(location.hash.slice(1));

// ---------- Categorías ----------

function filaCategoria(c, tipo) {
  const li = crear("li", "list-group-item");
  const fila = crear("div", "fila-datos");
  const izq = crear("div");
  const titulo = crear("div", "d-flex align-items-center gap-2 flex-wrap");
  titulo.append(crear("span", "fw-bold", c.nombre));
  if (c.propia) titulo.append(crear("span", "chip chip-propia", "Tuya"));
  if (c.nombre === SIN_CLASIFICAR) titulo.append(crear("span", "chip chip-pendiente", "Por ordenar"));
  const uso = c.en_uso === 0 ? "Sin usar" : c.en_uso === 1 ? "1 movimiento" : `${c.en_uso} movimientos`;
  izq.append(titulo, crear("div", "text-secondary small", uso));
  fila.append(izq);

  const der = crear("div", "d-flex align-items-center gap-1");
  if (c.nombre === SIN_CLASIFICAR && c.en_uso > 0) {
    const ir = crear("a", "btn btn-sm btn-primary", "Clasificar");
    ir.href = `/movimientos?tipo=${tipo === "gasto" ? "gastos" : "ingresos"}&categoria=${encodeURIComponent(SIN_CLASIFICAR)}`;
    der.append(ir);
  }
  if (c.propia) {
    const renombrar = crear("button", "btn btn-icon btn-sm btn-ghost-secondary");
    renombrar.type = "button";
    renombrar.setAttribute("aria-label", `Cambiar el nombre de ${c.nombre}`);
    renombrar.append(icono("editar", 16));
    renombrar.addEventListener("click", async () => {
      const r = await pedirCategoria({
        tipo,
        actual: c.nombre,
        guardar: ({ nombre }) => api(`/api/categorias/${tipo}/${encodeURIComponent(c.nombre)}`, { method: "PATCH", body: { nombre } }),
      });
      if (r) {
        aviso(`Ahora se llama «${r.nombre}».`);
        await cargarCategorias();
        await cargarTopes();
        await cargarFijos();
      }
    });
    const borrar = crear("button", "btn btn-icon btn-sm btn-ghost-danger");
    borrar.type = "button";
    borrar.setAttribute("aria-label", `Borrar ${c.nombre}`);
    borrar.append(icono("borrar", 16));
    borrar.addEventListener("click", async () => {
      if (!confirm(`¿Borrar la categoría «${c.nombre}»?`)) return;
      try {
        await api(`/api/categorias/${tipo}/${encodeURIComponent(c.nombre)}`, { method: "DELETE" });
        aviso(`Categoría «${c.nombre}» borrada.`);
        await cargarCategorias();
        await cargarTopes();
      } catch (e) {
        aviso(e.message, { error: true, duracion: 8000 });
      }
    });
    der.append(renombrar, borrar);
  }
  fila.append(der);
  li.append(fila);
  return li;
}

async function cargarCategorias() {
  const r = await api("/api/categorias");
  window.TG.categorias = r.gasto.map((c) => c.nombre);
  window.TG.categoriasIngreso = r.ingreso.map((c) => c.nombre);
  for (const tipo of ["gasto", "ingreso"]) {
    const lista = $("cats-" + tipo);
    lista.replaceChildren();
    r[tipo].forEach((c) => lista.append(filaCategoria(c, tipo)));
  }
  rellenarFijo(selFijo.value || "Hogar");
}

$("nueva-categoria").addEventListener("click", async () => {
  const c = await crearCategoriaInteractivo(null);
  if (c) {
    await cargarCategorias();
    await cargarTopes();
  }
});

// ---------- Topes ----------

const textoEstado = {
  ok: ["check", "Vas bien"],
  cerca: ["alerta", "Cerca del tope"],
  pasado: ["alerta", "Pasaste el tope"],
};

function pintarFilaTope(li, t) {
  li.replaceChildren();
  const cabecera = crear("div", "fila-datos");
  cabecera.append(crear("strong", "", t.categoria), crear("span", "text-secondary small", `Llevas ${soles(t.gastado_centimos)} este mes`));

  const controles = crear("div", "tope-controles");
  const entrada = crear("input", "form-control");
  entrada.type = "number";
  entrada.step = "0.01";
  entrada.min = "0.01";
  entrada.inputMode = "decimal";
  entrada.placeholder = "Sin tope";
  entrada.value = t.tope_centimos ? (t.tope_centimos / 100).toFixed(2) : "";
  entrada.setAttribute("aria-label", `Tope mensual para ${t.categoria} en soles`);
  const guardar = async () => {
    const valor = entrada.value.trim();
    try {
      if (!valor) {
        if (t.tope_centimos) {
          await api("/api/topes/" + encodeURIComponent(t.categoria), { method: "DELETE" });
          aviso(`Quitaste el tope de ${t.categoria}.`);
        }
      } else {
        if (!(parseFloat(valor) > 0)) throw new Error("El tope debe ser mayor a cero.");
        await api("/api/topes/" + encodeURIComponent(t.categoria), { method: "PUT", body: { monto: valor } });
        aviso(`Tope de ${t.categoria} guardado.`);
      }
      await cargarTopes();
    } catch (e) {
      aviso(e.message, { error: true });
    }
  };
  entrada.addEventListener("change", guardar);
  entrada.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      entrada.blur();
    }
  });
  const grupo = crear("div", "input-group");
  grupo.append(crear("span", "input-group-text", "S/"), entrada);
  controles.append(grupo);

  if (t.estado) {
    const [ico, texto] = textoEstado[t.estado];
    const chip = crear("span", "estado estado-" + t.estado);
    chip.append(icono(ico, 16), crear("span", "", `${texto} · ${t.porcentaje} %`));
    controles.append(chip);
  }
  li.append(cabecera, controles);

  if (t.estado) {
    const medidor = crear("div", "medidor mt-2");
    const relleno = crear("div", "relleno relleno-" + t.estado);
    relleno.style.width = Math.min(100, t.porcentaje) + "%";
    relleno.setAttribute("role", "progressbar");
    relleno.setAttribute("aria-label", `${t.categoria}: ${t.porcentaje}% del tope`);
    relleno.setAttribute("aria-valuenow", Math.min(100, t.porcentaje));
    relleno.setAttribute("aria-valuemin", "0");
    relleno.setAttribute("aria-valuemax", "100");
    medidor.append(relleno);
    const resto = t.restante_centimos >= 0 ? `Te quedan ${soles(t.restante_centimos)}` : `Te pasaste por ${soles(-t.restante_centimos)}`;
    li.append(medidor, crear("div", "text-secondary small mt-1", resto));
  }
}

async function cargarTopes() {
  const topes = await api("/api/topes");
  const lista = $("lista-topes");
  lista.replaceChildren();
  for (const t of topes) {
    const li = crear("li");
    pintarFilaTope(li, t);
    lista.append(li);
  }
}

// ---------- Gastos fijos ----------

const raiz = $("planificacion");
const mesActual = raiz.dataset.mesActual;
const selFijo = $("fijo-categoria");
const rellenarFijo = prepararSelectCategoria(selFijo, "gasto", { sinClasificar: false, valor: "Hogar" });

// Mientras escribes el concepto, se sugiere la categoría sola (tú puedes cambiarla).
let temporizadorSugerenciaFijo = null;
$("fijo-concepto").addEventListener("input", (ev) => {
  clearTimeout(temporizadorSugerenciaFijo);
  const concepto = ev.target.value.trim();
  if (concepto.length < 3) return;
  temporizadorSugerenciaFijo = setTimeout(async () => {
    try {
      const r = await api(`/api/sugerir?tipo=gasto&concepto=${encodeURIComponent(concepto)}`);
      if (r.categoria) selFijo.value = r.categoria;
    } catch (e) {}
  }, 250);
});

async function alternarHistorialFijo(f, contenedor, boton) {
  if (contenedor.childElementCount > 0) {
    contenedor.replaceChildren();
    boton.textContent = "Ver historial";
    return;
  }
  boton.textContent = "Ocultando…";
  const meses = await api("/api/fijos/" + f.id + "/historial");
  contenedor.replaceChildren();
  if (meses.length === 0) {
    contenedor.append(crear("div", "text-secondary small", "Todavía no se pagó ninguna vez."));
  } else {
    meses.forEach((m) => {
      const fila = crear("div", "fijo-historial-item");
      fila.append(crear("span", "", nombreMes(m.fecha.slice(0, 7), true)), crear("span", "monto", soles(m.monto_centimos)));
      contenedor.append(fila);
    });
  }
  boton.textContent = "Ocultar historial";
}

function filaFijo(f) {
  const li = crear("li", "list-group-item" + (f.activo ? "" : " fijo-inactivo"));
  const fila = crear("div", "fila-datos");
  const izq = crear("div");
  const pagadoEsteMes = f.ultimo_mes === mesActual;
  const linea2 = crear("div", "text-secondary small", `${f.categoria} · se anota el día ${f.dia} de cada mes`);
  izq.append(crear("div", "fw-bold text-break", f.concepto), linea2);
  if (f.activo) {
    const estado = crear("div", "mt-1 d-flex align-items-center gap-2 flex-wrap");
    estado.append(crear("span", "chip " + (pagadoEsteMes ? "chip-pagado" : "chip-pendiente"), pagadoEsteMes ? "Pagado este mes" : "Pendiente este mes"));
    if (!pagadoEsteMes) {
      const pagar = crear("button", "chip-enlace", "Pagar ahora");
      pagar.type = "button";
      pagar.addEventListener("click", async () => {
        try {
          await api("/api/fijos/" + f.id + "/pagar", { method: "POST" });
          aviso(`Pagado: ${f.concepto}.`);
          await cargarFijos();
        } catch (e) {
          aviso(e.message, { error: true });
        }
      });
      estado.append(pagar);
    }
    izq.append(estado);
  }
  const historialCont = crear("div", "fijo-historial");
  const verHistorial = crear("button", "fijo-ver-historial mt-1", "Ver historial");
  verHistorial.type = "button";
  verHistorial.addEventListener("click", () => alternarHistorialFijo(f, historialCont, verHistorial));
  izq.append(verHistorial, historialCont);

  const der = crear("div", "d-flex align-items-center gap-2");
  der.append(crear("div", "monto", soles(f.monto_centimos)));

  const interruptor = crear("label", "form-check form-switch m-0");
  const check = crear("input", "form-check-input");
  check.type = "checkbox";
  check.checked = f.activo;
  check.setAttribute("aria-label", `${f.concepto} activo`);
  check.addEventListener("change", async () => {
    try {
      await api("/api/fijos/" + f.id, { method: "PATCH", body: { activo: check.checked } });
      await cargarFijos();
    } catch (e) {
      check.checked = !check.checked;
      aviso(e.message, { error: true });
    }
  });
  interruptor.append(check);

  const borrar = crear("button", "btn btn-icon btn-sm btn-ghost-danger");
  borrar.type = "button";
  borrar.setAttribute("aria-label", `Borrar ${f.concepto}`);
  borrar.append(icono("borrar", 16));
  borrar.addEventListener("click", async () => {
    if (!confirm(`¿Seguro que quieres borrar el gasto fijo «${f.concepto}» (${soles(f.monto_centimos)})?`)) return;
    try {
      await api("/api/fijos/" + f.id, { method: "DELETE" });
      aviso(`Borrado: ${f.concepto}`, {
        accion: {
          texto: "Deshacer",
          fn: async () => {
            await api("/api/fijos", {
              method: "POST",
              body: { concepto: f.concepto, monto: f.monto_centimos / 100, categoria: f.categoria, dia: f.dia },
            });
            await cargarFijos();
          },
        },
      });
      await cargarFijos();
    } catch (e) {
      aviso(e.message, { error: true });
    }
  });
  der.append(interruptor, borrar);
  fila.append(izq, der);
  li.append(fila);
  return li;
}

async function cargarFijos() {
  const { items: fijos, total_centimos } = await api("/api/fijos");
  const lista = $("lista-fijos");
  lista.replaceChildren();
  $("fijos-vacio").hidden = fijos.length > 0;
  fijos.forEach((f) => lista.append(filaFijo(f)));
  $("fijos-total").textContent = soles(total_centimos);
}

$("form-fijo").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const error = $("fijo-error");
  error.hidden = true;
  const cuerpo = {
    concepto: $("fijo-concepto").value.trim(),
    monto: $("fijo-monto").value,
    dia: $("fijo-dia").value,
    categoria: selFijo.value,
  };
  if (!cuerpo.concepto || !(parseFloat(cuerpo.monto) > 0) || !(parseInt(cuerpo.dia, 10) >= 1)) {
    error.textContent = "Completa el concepto, el monto y el día del mes (1 a 31).";
    error.hidden = false;
    return;
  }
  try {
    await api("/api/fijos", { method: "POST", body: cuerpo });
    ev.target.reset();
    rellenarFijo("Hogar");
    aviso("Gasto fijo agregado.");
    await cargarFijos();
    $("fijo-concepto").focus();
  } catch (e) {
    error.textContent = e.message;
    error.hidden = false;
  }
});

cargarCategorias().catch((e) => aviso(e.message, { error: true }));
cargarTopes().catch((e) => aviso(e.message, { error: true }));
cargarFijos().catch((e) => aviso(e.message, { error: true }));
