const mensaje = $("mensaje");
const formPasos = $("form-pasos");
const montoCampo = $("monto");
const detalleCampo = $("detalle");


// ---------- Mensajes ----------

function limpiarMensaje() {
  mensaje.replaceChildren();
  mensaje.className = "mensaje";
  $("clasificar").replaceChildren();
}

function mostrarError(texto) {
  limpiarMensaje();
  mensaje.classList.add("error");
  mensaje.append(icono("alerta", 18), crear("span", "", texto));
}

function describir(c) {
  const fecha = c.fecha && c.fecha !== hoyISO() ? " · " + fechaRelativa(c.fecha).toLowerCase() : "";
  if (c.tipo === "ingreso") return `Ingreso: ${c.concepto} · +${soles(c.monto_centimos)}${fecha}`;
  if (c.tipo === "me_deben") return `${c.persona} te debe ${soles(c.monto_centimos)}`;
  if (c.tipo === "debo") return `Le debes ${soles(c.monto_centimos)} a ${c.persona}`;
  if (c.concepto === c.categoria) return `${c.categoria} · ${soles(c.monto_centimos)}${fecha}`;
  return `${c.concepto} · ${soles(c.monto_centimos)} · ${c.categoria}${fecha}`;
}

function endpointDe(c) {
  if (c.tipo === "gasto") return "/api/gastos/" + c.id;
  if (c.tipo === "ingreso") return "/api/ingresos/" + c.id;
  return "/api/deudas/" + c.id;
}

// Cuando la app no reconoce el gasto, pregunta en el momento en qué categoría va y aprende.
function bloqueClasificar(c) {
  const tipoCat = c.tipo === "ingreso" ? "ingreso" : "gasto";
  const tabla = c.tipo === "ingreso" ? "ingresos" : "gastos";
  const sinDetalle = c.concepto === "Sin concepto";
  const bloque = crear("div", "clasificar");
  const pregunta = crear("div", "clasificar-pregunta");
  pregunta.append(
    icono("alerta", 18),
    crear("span", "", sinDetalle ? `¿En qué categoría va este ${tipoCat} de ${soles(c.monto_centimos)}?` : `No sé en qué categoría va «${c.concepto}». ¿Cuál es?`)
  );

  const elegir = async (categoria) => {
    try {
      const cambios = { categoria };
      if (sinDetalle) cambios.concepto = categoria; // sin detalle, el gasto se llama como su categoría
      await api(`/api/${tabla}/${c.id}`, { method: "PATCH", body: cambios });
      bloque.replaceChildren(
        icono("check", 18),
        crear("span", "", sinDetalle ? `Listo: queda en ${categoria}.` : `Listo: «${c.concepto}» queda en ${categoria}. La próxima vez lo pongo solo.`)
      );
      bloque.classList.add("clasificar-listo");
      await cargar();
    } catch (e) {
      aviso(e.message, { error: true });
    }
  };

  const chips = crear("div", "clasificar-chips");
  for (const cat of categoriasElegibles(tipoCat)) {
    const b = crear("button", "chip-cat", cat);
    b.type = "button";
    b.addEventListener("click", () => elegir(cat));
    chips.append(b);
  }
  const nueva = crear("button", "chip-cat chip-cat-nueva", "＋ Nueva categoría");
  nueva.type = "button";
  nueva.addEventListener("click", async () => {
    const creada = await crearCategoriaInteractivo(tipoCat);
    if (creada) await elegir(creada.nombre);
  });
  chips.append(nueva);
  bloque.append(pregunta, chips);
  return bloque;
}

function mostrarGuardado(creados) {
  limpiarMensaje();
  const visibles = creados.filter((c) => !c.auxiliar);
  const lista = crear("div", "mensaje-lista");
  lista.append(icono("check", 18));
  const textos = crear("div", "mensaje-textos");
  visibles.forEach((c) => textos.append(crear("div", "", describir(c))));
  lista.append(textos);
  const deshacer = crear("button", "btn btn-sm btn-outline-secondary", "Deshacer");
  deshacer.type = "button";
  deshacer.addEventListener("click", async () => {
    try {
      for (const c of creados) await api(endpointDe(c), { method: "DELETE" });
      limpiarMensaje();
      mensaje.append(crear("span", "text-secondary", "Anulado."));
      await cargar();
    } catch (e) {
      mostrarError(e.message);
    }
  });
  mensaje.append(lista, deshacer);
  creados.filter((c) => c.categoria_dudosa).forEach((c) => $("clasificar").append(bloqueClasificar(c)));
}

// ---------- Enlace pequeño (lo básico son los 3 pasos de arriba) ----------

// En el celular el teclado no se abre solo: así ves todo el formulario antes de escribir.
const esTactil = window.matchMedia("(pointer: coarse)").matches;
function enfocarMonto() {
  if (!esTactil) montoCampo.focus();
}

$("abrir-detalle").addEventListener("click", () => {
  $("detalle-caja").hidden = false;
  $("abrir-detalle").hidden = true;
  detalleCampo.focus();
});

// ---------- Paso 2: fecha ----------

let fechaElegida = null; // null = hoy
const opcionesFecha = $("fecha-opciones");
const fechaOtra = $("fecha-otra");

function etiquetaFecha(iso) {
  const dia = fechaDe(iso).toLocaleDateString("es-PE", { weekday: "long", day: "numeric", month: "long" });
  const rel = diasDesdeHoy(iso);
  return rel === 1 ? `de ayer (${dia})` : rel === 2 ? `de anteayer (${dia})` : `del ${dia}`;
}

function pintarFechaElegida() {
  const esHoy = !fechaElegida || fechaElegida === hoyISO();
  $("nota-fecha").hidden = esHoy;
  if (!esHoy) $("nota-fecha-texto").textContent = etiquetaFecha(fechaElegida);
}

function elegirFecha(valor) {
  opcionesFecha.querySelectorAll("[role=radio]").forEach((b) => b.setAttribute("aria-checked", b.dataset.dia === valor ? "true" : "false"));
  fechaOtra.hidden = valor !== "otro";
  if (valor === "otro") {
    fechaElegida = fechaOtra.value || null;
    fechaOtra.focus();
  } else {
    fechaElegida = valor === "0" ? null : isoHaceDias(Number(valor));
  }
  pintarFechaElegida();
}

opcionesFecha.querySelectorAll("[role=radio]").forEach((b) => b.addEventListener("click", () => elegirFecha(b.dataset.dia)));
fechaOtra.addEventListener("change", () => {
  fechaElegida = fechaOtra.value && !fechaOtra.validity.rangeOverflow ? fechaOtra.value : null;
  pintarFechaElegida();
});
$("volver-hoy").addEventListener("click", () => elegirFecha("0"));

// ---------- Paso 3: categoría (botones a la vista) ----------

let categoriaElegida = "";
let categoriaSugerida = "";

const dlgMas = $("dlg-mas");

function categoriasVisibles() {
  const validas = categoriasElegibles("gasto");
  const usadas = (window.TG.masUsadas.gasto || []).filter((c) => validas.includes(c));
  const lista = usadas.length ? [...usadas] : validas.slice(0, 6);
  for (const extra of [categoriaElegida, categoriaSugerida]) if (extra && !lista.includes(extra)) lista.push(extra);
  return lista;
}

function pintarCategorias() {
  const caja = $("cat-chips");
  caja.classList.remove("pide-elegir");
  caja.replaceChildren();
  for (const c of categoriasVisibles()) {
    const elegida = c === categoriaElegida;
    const sugerida = !categoriaElegida && c === categoriaSugerida;
    const b = crear("button", "chip-cat chip-cat-grande" + (sugerida ? " sugerida" : ""), c);
    b.type = "button";
    b.setAttribute("role", "radio");
    b.setAttribute("aria-checked", elegida ? "true" : "false");
    if (sugerida) b.title = "La adiviné por el detalle. Toca otra si no es.";
    b.addEventListener("click", () => {
      categoriaElegida = elegida ? "" : c;
      pintarCategorias();
    });
    caja.append(b);
  }
  const mas = crear("button", "chip-cat chip-cat-grande chip-cat-mas", "Más…");
  mas.type = "button";
  mas.addEventListener("click", abrirMas);
  caja.append(mas);
}

function abrirMas() {
  const caja = $("cat-todas");
  caja.replaceChildren();
  for (const c of categoriasElegibles("gasto")) {
    const b = crear("button", "chip-cat chip-cat-grande", c);
    b.type = "button";
    b.setAttribute("aria-pressed", c === categoriaElegida ? "true" : "false");
    b.addEventListener("click", () => {
      categoriaElegida = c;
      dlgMas.close();
      pintarCategorias();
    });
    caja.append(b);
  }
  const nueva = crear("button", "chip-cat chip-cat-grande chip-cat-nueva", "＋ Nueva categoría");
  nueva.type = "button";
  nueva.addEventListener("click", async () => {
    dlgMas.close();
    const creada = await crearCategoriaInteractivo("gasto");
    if (creada) {
      categoriaElegida = creada.nombre;
      pintarCategorias();
    }
  });
  caja.append(nueva);
  dlgMas.showModal();
}
$("dlg-mas-cerrar").addEventListener("click", () => dlgMas.close());
dlgMas.addEventListener("click", (ev) => {
  if (ev.target === dlgMas) dlgMas.close();
});
pintarCategorias();

// Mientras escribes el detalle, se marca la categoría que la app cree que es (tú decides).
let temporizadorSugerencia = null;
detalleCampo.addEventListener("input", () => {
  clearTimeout(temporizadorSugerencia);
  temporizadorSugerencia = setTimeout(async () => {
    const concepto = detalleCampo.value.trim();
    let sugerida = "";
    if (concepto.length >= 3) {
      try {
        const r = await api(`/api/sugerir?tipo=gasto&concepto=${encodeURIComponent(concepto)}`);
        sugerida = r.categoria || "";
      } catch (e) {}
    }
    if (sugerida !== categoriaSugerida) {
      categoriaSugerida = sugerida;
      pintarCategorias();
    }
  }, 250);
});

// ---------- Guardar ----------

formPasos.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const monto = montoCampo.value.trim();
  if (!(parseFloat(monto) > 0)) {
    mostrarError("Escribe cuánto fue (un monto mayor a cero).");
    montoCampo.focus();
    return;
  }
  if (opcionesFecha.querySelector("[aria-checked=true]").dataset.dia === "otro" && !fechaElegida) {
    mostrarError("Elige el día en el calendario (o toca Hoy).");
    fechaOtra.focus();
    return;
  }
  const detalle = detalleCampo.value.trim();
  const concepto = detalle || categoriaElegida;
  if (!concepto) {
    mostrarError("Falta el paso 3: toca en qué categoría fue.");
    const caja = $("cat-chips");
    caja.classList.add("pide-elegir");
    caja.scrollIntoView({ block: "center", behavior: "smooth" });
    return;
  }
  const cuerpo = { concepto, monto };
  if (fechaElegida) cuerpo.fecha = fechaElegida;
  if (categoriaElegida) cuerpo.categoria = categoriaElegida;
  try {
    const g = await api("/api/gastos", { method: "POST", body: cuerpo });
    montoCampo.value = "";
    detalleCampo.value = "";
    categoriaElegida = "";
    categoriaSugerida = "";
    pintarCategorias(); // la fecha se queda por si estás poniéndote al día
    mostrarGuardado([{ tipo: "gasto", ...g, categoria_dudosa: g.categoria === SIN_CLASIFICAR }]);
    await cargar();
  } catch (e) {
    mostrarError(e.message);
  }
  enfocarMonto();
});

// ---------- Panel ----------

function pintarSinClasificar(r) {
  const sc = r.sin_clasificar;
  $("bloque-sinclasificar").hidden = sc.n === 0;
  if (!sc.n) return;
  $("sc-titulo").textContent = sc.n === 1 ? "Tienes 1 gasto sin clasificar este mes" : `Tienes ${sc.n} gastos sin clasificar este mes`;
  $("sc-detalle").textContent = `Suman ${soles(sc.total_centimos)}. Dile a cada uno en qué categoría va y la app aprende para la próxima.`;
  $("sc-enlace").href = "/movimientos?categoria=" + encodeURIComponent(SIN_CLASIFICAR);
}

function pintarDisponible(r) {
  const hayIngresos = r.ingresado_mes_centimos > 0;
  const negativo = r.disponible_centimos < 0;
  $("disp-ingresos").textContent = soles(r.ingresado_mes_centimos);
  $("disp-gastos").textContent = soles(r.gastado_mes_centimos);

  if (!hayIngresos) {
    $("disp-etiqueta").textContent = "Gastado este mes";
    $("disp-monto").textContent = soles(r.gastado_mes_centimos);
    $("disp-detalle").textContent = "Anota tu sueldo o lo que te entra (botón «Anotar ingreso» abajo) para saber cuánto te queda.";
    $("disp-barra-caja").hidden = true;
    return;
  }

  $("disp-etiqueta").textContent = negativo ? "Este mes gastaste más de lo que te entró" : "Te quedan este mes";
  $("disp-monto").textContent = soles(r.disponible_centimos);
  if (negativo) {
    $("disp-detalle").textContent = "Por ahora no hay margen. Revisa en qué se fue la plata en Resumen.";
  } else if (r.disponible_centimos === 0) {
    $("disp-detalle").textContent = "Ya no te queda nada de lo que ingresó este mes.";
  } else {
    const dias = r.dias_restantes === 1 ? "queda 1 día" : `quedan ${r.dias_restantes} días`;
    $("disp-detalle").textContent = `Puedes gastar hasta ${soles(r.por_dia_centimos)} por día (${dias}, contando hoy).`;
  }
  const pct = Math.min(100, Math.round((100 * r.gastado_mes_centimos) / r.ingresado_mes_centimos));
  $("disp-barra-caja").hidden = false;
  $("disp-barra").style.width = pct + "%";
  $("disp-barra").setAttribute("aria-valuenow", pct);
  $("disp-barra").setAttribute("aria-valuetext", `${pct}% de tus ingresos ya se gastó`);
}

function pintarHoy(r) {
  $("hoy-monto").textContent = soles(r.gasto_hoy_centimos);
  $("hoy-detalle").textContent = r.n_hoy ? (r.n_hoy === 1 ? "1 movimiento" : `${r.n_hoy} movimientos`) : "";
  $("recordatorio").hidden = !r.sin_registro_hoy;

  const caja = $("resumen-deudas");
  caja.replaceChildren();
  const d = r.deudas;
  if (d.me_deben_centimos > 0) {
    const a = crear("a", "chip-enlace", `Te deben ${soles(d.me_deben_centimos)}`);
    a.href = "/deudas";
    caja.append(a);
  }
  if (d.debo_centimos > 0) {
    const a = crear("a", "chip-enlace", `Debes ${soles(d.debo_centimos)}`);
    a.href = "/deudas";
    caja.append(a);
  }
}

function pintarAlertas(r) {
  $("bloque-alertas").hidden = r.alertas.length === 0;
  const lista = $("alertas");
  lista.replaceChildren();
  for (const t of r.alertas) {
    const li = crear("li", "list-group-item");
    const fila = crear("div", "fila-datos");
    const estado = crear("span", "estado estado-" + t.estado);
    estado.append(icono("alerta", 16), crear("span", "", t.estado === "pasado" ? "Pasaste el tope" : "Cerca del tope"));
    fila.append(crear("strong", "", t.categoria), estado);
    const detalle = crear("div", "text-secondary small mt-1", `${soles(t.gastado_centimos)} de ${soles(t.tope_centimos)} (${t.porcentaje} %)`);
    const medidor = crear("div", "medidor mt-2");
    const relleno = crear("div", "relleno relleno-" + t.estado);
    relleno.style.width = Math.min(100, t.porcentaje) + "%";
    medidor.append(relleno);
    li.append(fila, detalle, medidor);
    lista.append(li);
  }
}

function pintarFrecuentes(r) {
  $("bloque-frecuentes").hidden = r.frecuentes.length === 0;
  const caja = $("frecuentes");
  caja.replaceChildren();
  for (const f of r.frecuentes) {
    const b = crear("button", "chip-frecuente");
    b.type = "button";
    b.title = `Lo anotaste ${f.veces} veces`;
    b.append(crear("span", "", f.concepto), crear("strong", "", soles(f.monto_centimos)));
    b.addEventListener("click", async () => {
      b.disabled = true;
      try {
        const g = await api("/api/gastos", {
          method: "POST",
          body: { concepto: f.concepto, monto: f.monto_centimos / 100, categoria: f.categoria },
        });
        mostrarGuardado([{ tipo: "gasto", ...g }]);
        await cargar();
      } catch (e) {
        mostrarError(e.message);
      } finally {
        b.disabled = false;
      }
    });
    caja.append(b);
  }
}

function pintarFijos(r) {
  $("bloque-fijos").hidden = r.proximos_fijos.length === 0;
  const lista = $("proximos-fijos");
  lista.replaceChildren();
  for (const f of r.proximos_fijos) {
    const li = crear("li", "list-group-item");
    const fila = crear("div", "fila-datos");
    const izq = crear("div");
    izq.append(
      crear("div", "fw-bold", f.concepto),
      crear("div", "text-secondary small", f.faltan_dias === 1 ? "Mañana" : `En ${f.faltan_dias} días (día ${f.dia})`)
    );
    fila.append(izq, crear("div", "monto", soles(f.monto_centimos)));
    li.append(fila);
    lista.append(li);
  }
}

let anotadosExpandido = false;
const LIMITE_ANOTADOS = 4;

function pintarAnotados(r) {
  const lista = $("anotados");
  lista.replaceChildren();
  $("anotados-vacio").hidden = r.anotados_hoy.length > 0;
  const items = anotadosExpandido ? r.anotados_hoy : r.anotados_hoy.slice(0, LIMITE_ANOTADOS);
  for (const m of items) {
    const esIngreso = m.tipo === "ingreso";
    const li = crear("li", "list-group-item");
    const fila = crear("div", "fila-datos");
    const izq = crear("div");
    const detalle = [];
    if (m.concepto !== m.categoria) detalle.push(m.categoria);
    if (m.fecha !== hoyISO()) detalle.push("de " + fechaRelativa(m.fecha).toLowerCase());
    izq.append(crear("div", "fw-bold text-break", m.concepto));
    if (detalle.length) izq.append(crear("div", "text-secondary small", detalle.join(" · ")));
    const der = crear("div", "d-flex align-items-center gap-2");
    der.append(crear("div", "monto" + (esIngreso ? " monto-ingreso" : ""), (esIngreso ? "+" : "") + soles(m.monto_centimos)));
    const borrar = crear("button", "btn btn-icon btn-sm btn-ghost-danger");
    borrar.type = "button";
    borrar.setAttribute("aria-label", `Borrar ${m.concepto}`);
    borrar.append(icono("borrar", 16));
    borrar.addEventListener("click", async () => {
      try {
        await borrarConDeshacer(esIngreso ? "ingresos" : "gastos", { ...m }, cargar);
      } catch (e) {
        mostrarError(e.message);
      }
    });
    der.append(borrar);
    fila.append(izq, der);
    li.append(fila);
    lista.append(li);
  }
  const restantes = r.anotados_hoy.length - LIMITE_ANOTADOS;
  if (restantes > 0) {
    const li = crear("li", "list-group-item text-center");
    const boton = crear("button", "btn btn-link btn-sm", anotadosExpandido ? "Ver menos" : `Ver ${restantes} más`);
    boton.type = "button";
    boton.addEventListener("click", () => {
      anotadosExpandido = !anotadosExpandido;
      pintarAnotados(r);
    });
    li.append(boton);
    lista.append(li);
  }
}

// "Repetir con un toque" y "Se vienen estos pagos" comparten fila a media
// pantalla cada uno; si solo uno de los dos tiene datos, que ocupe todo el
// ancho en vez de dejar la mitad de la fila vacía.
function ajustarAnchoBloques() {
  const frecuentes = $("bloque-frecuentes");
  const fijos = $("bloque-fijos");
  const ambos = !frecuentes.hidden && !fijos.hidden;
  for (const el of [frecuentes, fijos]) {
    el.classList.toggle("col-lg-6", ambos);
    el.classList.toggle("col-12", !ambos);
  }
}

async function cargar() {
  const r = await api("/api/inicio");
  pintarSinClasificar(r);
  pintarDisponible(r);
  pintarHoy(r);
  pintarAlertas(r);
  pintarFrecuentes(r);
  pintarFijos(r);
  ajustarAnchoBloques();
  pintarAnotados(r);
}

enfocarMonto();
cargar().catch((e) => mostrarError(e.message));
