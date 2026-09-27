const TITULOS = { gasto: "Gasto borrado", ingreso: "Ingreso borrado", deuda: "Deuda borrada",
                  fijo: "Gasto fijo borrado", categoria: "Categoría borrada" };

function cuandoSeBorro(iso) {
  const fecha = new Date(iso);
  const dia = fecha.toLocaleDateString("es-PE", { day: "numeric", month: "short", year: "numeric" });
  const hora = fecha.toLocaleTimeString("es-PE", { hour: "numeric", minute: "2-digit" });
  return `${dia}, ${hora}`;
}

function filaHistorial(h) {
  const li = crear("div", "mov");
  const izq = crear("div");
  const titulo = crear("div", "d-flex align-items-center gap-2 flex-wrap");
  titulo.append(crear("span", "fw-bold", h.descripcion), crear("span", "chip", TITULOS[h.tipo] || h.tipo));
  const detalles = [];
  if (h.detalle) detalles.push(h.detalle);
  if (h.fecha) {
    const rel = fechaRelativa(h.fecha);
    detalles.push(rel === "Hoy" ? "de hoy" : rel === "Ayer" ? "de ayer" : "del " + rel);
  }
  detalles.push("borrado el " + cuandoSeBorro(h.borrado_en));
  izq.append(titulo, crear("div", "text-secondary small", detalles.join(" · ")));
  li.append(izq);
  if (h.monto_centimos !== null && h.monto_centimos !== undefined) {
    li.append(crear("div", "monto", soles(h.monto_centimos)));
  }
  return li;
}

async function cargar() {
  const items = await api("/api/historial");
  const lista = $("lista");
  lista.replaceChildren();
  $("vacio").hidden = items.length > 0;
  items.forEach((h) => lista.append(filaHistorial(h)));
}

cargar().catch((e) => aviso(e.message, { error: true }));
