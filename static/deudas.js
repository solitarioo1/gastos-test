let tipoNuevo = "me_deben";

const verPagadas = $("ver-pagadas");

// ---------- Selector "Me deben / Yo debo" ----------

function elegirTipo(tipo) {
  tipoNuevo = tipo;
  document.querySelectorAll("#form-deuda [role=radio]").forEach((b) => b.setAttribute("aria-checked", b.dataset.tipo === tipo ? "true" : "false"));
  $("d-persona").placeholder = tipo === "me_deben" ? "Juan" : "Bodega de la esquina";
  $("d-ayuda").textContent =
    tipo === "me_deben"
      ? "Si prestas dinero, se anota también como un gasto en “Deudas”. Cuando te lo devuelvan, entra como ingreso."
      : "Lo que debes no toca tus gastos hasta que lo pagues. Ahí se anota como gasto en “Deudas”.";
}
document.querySelectorAll("#form-deuda [role=radio]").forEach((b) => b.addEventListener("click", () => elegirTipo(b.dataset.tipo)));

// ---------- Lista ----------

function filaDeuda(d) {
  const pagada = Boolean(d.pagada_fecha);
  const meDeben = d.tipo === "me_deben";
  const li = crear("li", "list-group-item" + (pagada ? " fijo-inactivo" : ""));
  const fila = crear("div", "fila-datos");

  const izq = crear("div");
  const titulo = crear("div", "d-flex align-items-center gap-2 flex-wrap");
  titulo.append(crear("span", "fw-bold text-break", d.persona), crear("span", "chip", meDeben ? "Te debe" : "Le debes"));
  const nota = d.nota ? ` · ${d.nota}` : "";
  izq.append(
    titulo,
    crear("div", "text-secondary small", pagada ? `Pagada el ${fechaDe(d.pagada_fecha).toLocaleDateString("es-PE", { day: "numeric", month: "short" })}${nota}` : `${fechaRelativa(d.fecha)}${nota}`)
  );

  const der = crear("div", "d-flex align-items-center gap-2");
  der.append(crear("div", "monto", soles(d.monto_centimos)));
  if (!pagada) {
    const pagar = crear("button", "btn btn-sm btn-primary", meDeben ? "Ya me pagó" : "Ya pagué");
    pagar.type = "button";
    pagar.addEventListener("click", async () => {
      pagar.disabled = true;
      try {
        const r = await api(`/api/deudas/${d.id}/pagar`, { method: "POST" });
        aviso(meDeben ? `Anotado como ingreso: ${r.movimiento.concepto}.` : `Anotado como gasto: ${r.movimiento.concepto}.`);
        await cargar();
      } catch (e) {
        pagar.disabled = false;
        aviso(e.message, { error: true });
      }
    });
    der.append(pagar);
  }
  const borrar = crear("button", "btn btn-icon btn-sm btn-ghost-danger");
  borrar.type = "button";
  borrar.setAttribute("aria-label", `Borrar deuda de ${d.persona}`);
  borrar.append(icono("borrar", 16));
  borrar.addEventListener("click", async () => {
    if (!confirm(`¿Borrar la deuda de ${d.persona} por ${soles(d.monto_centimos)}? Los movimientos ya anotados no se borran.`)) return;
    try {
      await api("/api/deudas/" + d.id, { method: "DELETE" });
      aviso("Deuda borrada.");
      await cargar();
    } catch (e) {
      aviso(e.message, { error: true });
    }
  });
  der.append(borrar);

  fila.append(izq, der);
  li.append(fila);
  return li;
}

async function cargar() {
  const r = await api("/api/deudas" + (verPagadas.checked ? "?pagadas=1" : ""));
  const res = r.resumen;
  $("total-me-deben").textContent = soles(res.me_deben_centimos);
  $("n-me-deben").textContent = res.n_me_deben ? (res.n_me_deben === 1 ? "1 persona" : `${res.n_me_deben} deudas`) : "Nadie te debe";
  $("total-debo").textContent = soles(res.debo_centimos);
  $("n-debo").textContent = res.n_debo ? (res.n_debo === 1 ? "1 deuda" : `${res.n_debo} deudas`) : "No debes nada";

  const lista = $("lista-deudas");
  lista.replaceChildren();
  $("vacio").hidden = r.deudas.length > 0;
  r.deudas.forEach((d) => lista.append(filaDeuda(d)));
}

verPagadas.addEventListener("change", cargar);

// ---------- Formulario ----------

$("form-deuda").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const error = $("d-error");
  error.hidden = true;
  const cuerpo = {
    tipo: tipoNuevo,
    persona: $("d-persona").value.trim(),
    monto: $("d-monto").value,
    fecha: $("d-fecha").value,
    nota: $("d-nota").value.trim(),
  };
  if (!cuerpo.persona || !(parseFloat(cuerpo.monto) > 0) || !cuerpo.fecha) {
    error.textContent = "Escribe el nombre, un monto mayor a cero y la fecha.";
    error.hidden = false;
    return;
  }
  try {
    await api("/api/deudas", { method: "POST", body: cuerpo });
    ev.target.reset();
    $("d-fecha").value = window.TG.hoy;
    aviso("Deuda anotada.");
    await cargar();
    $("d-persona").focus();
  } catch (e) {
    error.textContent = e.message;
    error.hidden = false;
  }
});

elegirTipo("me_deben");
$("d-fecha").value = window.TG.hoy;
cargar().catch((e) => aviso(e.message, { error: true }));
