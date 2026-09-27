const raiz = $("resumen");
const MES_ACTUAL = raiz.dataset.mesActual;
let mes = MES_ACTUAL;
let datos = null;
let anchoDibujado = 0;

function svgEl(nombre, atributos = {}, clase) {
  const e = document.createElementNS(NS_SVG, nombre);
  for (const [k, v] of Object.entries(atributos)) e.setAttribute(k, v);
  if (clase) e.setAttribute("class", clase);
  return e;
}

// Escala con pasos limpios (1, 2, 5 × 10^n) y unos 4 tramos.
function escala(maxSoles) {
  const bruto = maxSoles / 4;
  const potencia = Math.pow(10, Math.max(0, Math.floor(Math.log10(bruto))));
  const paso = [1, 2, 5, 10].map((f) => f * potencia).find((p) => p >= bruto);
  return { paso, tope: Math.ceil(maxSoles / paso) * paso };
}

// Columna con borde superior redondeado (4 px) y base recta.
function rutaColumna(x, y, ancho, alto) {
  const r = Math.min(4, ancho / 2, alto);
  return (
    `M${x},${y + alto}V${y + r}Q${x},${y} ${x + r},${y}H${x + ancho - r}` +
    `Q${x + ancho},${y} ${x + ancho},${y + r}V${y + alto}Z`
  );
}

function dibujarGrafico(r) {
  const cont = $("grafico");
  cont.replaceChildren();
  const n = r.por_dia_centimos.length;
  const hayDatos = r.n_gastos > 0 && n > 0;
  $("grafico-vacio").hidden = hayDatos;
  $("vista-tabla").hidden = !hayDatos;
  if (!hayDatos) return;

  const W = cont.clientWidth || 600;
  const H = 240;
  const m = { izq: 52, der: 8, sup: 26, inf: 26 };
  const anchoPlot = W - m.izq - m.der;
  const altoPlot = H - m.sup - m.inf;
  const valores = r.por_dia_centimos.map((c) => c / 100);
  const { paso, tope } = escala(Math.max(...valores));
  const banda = anchoPlot / n;
  const anchoBarra = Math.max(2, Math.min(24, banda - 2));
  const y = (v) => m.sup + altoPlot - (v / tope) * altoPlot;
  const centroX = (i) => m.izq + banda * i + banda / 2;

  const mayor = r.dia_mayor;
  const svg = svgEl("svg", {
    width: W,
    height: H,
    viewBox: `0 0 ${W} ${H}`,
    role: "img",
    "aria-label": `Gasto por día en ${nombreMes(r.mes, true)}. Mayor gasto: día ${mayor.dia}, ${soles(mayor.total_centimos)}.`,
  });

  const tramos = Math.round(tope / paso);
  for (let k = 0; k <= tramos; k++) {
    const v = k * paso;
    const yy = y(v);
    svg.append(svgEl("line", { x1: m.izq, x2: W - m.der, y1: yy, y2: yy }, v === 0 ? "base" : "rejilla"));
    const t = svgEl("text", { x: m.izq - 8, y: yy + 4, "text-anchor": "end" }, "eje");
    t.textContent = "S/ " + v.toLocaleString("es-PE");
    svg.append(t);
  }

  const cada = Math.ceil(n / Math.max(1, Math.floor(anchoPlot / 30)));
  for (let i = 0; i < n; i++) {
    if (i % cada !== 0) continue;
    const t = svgEl("text", { x: centroX(i), y: H - 8, "text-anchor": "middle" }, "eje");
    t.textContent = i + 1;
    svg.append(t);
  }

  const barras = [];
  valores.forEach((v, i) => {
    if (v <= 0) {
      barras.push(null);
      return;
    }
    const alto = Math.max(2, (v / tope) * altoPlot);
    const b = svgEl("path", { d: rutaColumna(centroX(i) - anchoBarra / 2, m.sup + altoPlot - alto, anchoBarra, alto) }, "barra");
    barras.push(b);
    svg.append(b);
  });

  const etiqueta = svgEl("text", { y: y(mayor.total_centimos / 100) - 8, "text-anchor": "middle" }, "dato");
  etiqueta.setAttribute("x", Math.min(Math.max(centroX(mayor.dia - 1), m.izq + 34), W - m.der - 34));
  etiqueta.textContent = soles(mayor.total_centimos);
  svg.append(etiqueta);

  const tip = crear("div", "tip");
  tip.hidden = true;
  const tipValor = crear("div", "tip-valor");
  const tipDia = crear("div", "tip-dia");
  tip.append(tipValor, tipDia);
  let activa = null;

  function mostrar(i) {
    if (activa !== null && barras[activa]) barras[activa].classList.remove("activa");
    activa = i;
    if (barras[i]) barras[i].classList.add("activa");
    const fecha = new Date(partesMes(r.mes).anio, partesMes(r.mes).num - 1, i + 1);
    tipValor.textContent = soles(r.por_dia_centimos[i]);
    tipDia.textContent = fecha.toLocaleDateString("es-PE", { weekday: "long", day: "numeric", month: "long" });
    tip.hidden = false;
    const izquierda = Math.min(Math.max(centroX(i) - tip.offsetWidth / 2, 0), W - tip.offsetWidth);
    tip.style.left = izquierda + "px";
    tip.style.top = Math.max(0, y(valores[i]) - tip.offsetHeight - 10) + "px";
  }

  function ocultar() {
    if (activa !== null && barras[activa]) barras[activa].classList.remove("activa");
    activa = null;
    tip.hidden = true;
  }

  valores.forEach((v, i) => {
    const zona = svgEl("rect", { x: m.izq + banda * i, y: m.sup, width: banda, height: altoPlot }, "zona");
    if (v > 0) {
      zona.setAttribute("tabindex", "0");
      zona.setAttribute("aria-label", `Día ${i + 1}: ${soles(r.por_dia_centimos[i])}`);
    }
    zona.addEventListener("pointerenter", () => mostrar(i));
    zona.addEventListener("pointermove", () => mostrar(i));
    zona.addEventListener("pointerdown", () => mostrar(i));
    zona.addEventListener("pointerleave", ocultar);
    zona.addEventListener("focus", () => mostrar(i));
    zona.addEventListener("blur", ocultar);
    svg.append(zona);
  });

  cont.append(svg, tip);
  anchoDibujado = W;
}

function dibujarTabla(r) {
  const cuerpo = $("tabla-dias");
  cuerpo.replaceChildren();
  r.por_dia_centimos.forEach((c, i) => {
    if (c <= 0) return;
    const fila = crear("tr");
    fila.append(crear("td", "", String(i + 1)), crear("td", "text-end monto", soles(c)));
    cuerpo.append(fila);
  });
}

function dibujarCabecera(r) {
  $("mes-etiqueta").textContent = nombreMes(r.mes, true);
  $("mes-siguiente").disabled = r.mes >= MES_ACTUAL;
  $("hero-etiqueta").textContent = "Gastado en " + nombreMes(r.mes, true);
  $("total").textContent = soles(r.total_centimos);

  const anterior = nombreMes(r.mes_anterior, false);
  let comparacion = "";
  if (r.total_centimos > 0) {
    if (r.total_mes_anterior_centimos === 0) {
      comparacion = "Sin gastos registrados en " + anterior + " para comparar";
    } else {
      const diff = r.total_centimos - r.total_mes_anterior_centimos;
      const sufijo = r.mes === MES_ACTUAL ? " (mes completo)" : "";
      comparacion =
        diff === 0
          ? "Igual que en " + anterior + sufijo
          : soles(Math.abs(diff)) + (diff > 0 ? " más" : " menos") + " que en " + anterior + sufijo;
    }
  }
  $("comparacion").textContent = comparacion;
  $("detalle").textContent = r.n_gastos
    ? r.n_gastos + (r.n_gastos === 1 ? " gasto" : " gastos") + " en " +
      r.dias_con_registro + (r.dias_con_registro === 1 ? " día" : " días") + " con registro"
    : "";

  const hayIngresos = r.ingresos_centimos > 0;
  $("balance").hidden = !hayIngresos;
  if (hayIngresos) {
    const sobra = r.ingresos_centimos - r.total_centimos;
    $("bal-ingresos").textContent = soles(r.ingresos_centimos);
    $("bal-etiqueta").textContent = sobra >= 0 ? "Te sobran" : "Te pasaste por";
    $("bal-monto").textContent = soles(Math.abs(sobra));
  }
}

function dibujarEstadisticas(r) {
  $("est-dias").textContent = r.dias_transcurridos;
  $("est-con-gasto").textContent = r.dias_con_registro;
  $("est-promedio").textContent = soles(r.promedio_diario_centimos);
  $("est-mayor").textContent = r.dia_mayor ? "Día " + r.dia_mayor.dia : "—";
  $("est-mayor-monto").textContent = r.dia_mayor ? soles(r.dia_mayor.total_centimos) : "";
}

function dibujarCategorias(r) {
  const lista = $("barras");
  lista.replaceChildren();
  $("vacio").hidden = r.n_gastos > 0;
  $("destacada").hidden = !r.categoria_top;
  if (r.categoria_top) $("destacada").textContent = "Lo que más pesa: " + r.categoria_top;

  for (const c of r.categorias) {
    const li = crear("li");
    const fila = crear("div", "fila-datos");
    const nombre = crear("span", "", c.categoria);
    if (c.categoria === SIN_CLASIFICAR) {
      const enlace = crear("a", "chip chip-pendiente ms-2", "Clasificar");
      enlace.href = `/movimientos?categoria=${encodeURIComponent(SIN_CLASIFICAR)}&mes=${r.mes}`;
      nombre.append(enlace);
    }
    fila.append(nombre, crear("span", "text-secondary monto", soles(c.total_centimos) + " · " + c.porcentaje + "%"));
    const pista = crear("div", "medidor");
    const relleno = crear("div", "relleno");
    relleno.setAttribute("role", "progressbar");
    relleno.setAttribute("aria-label", c.categoria);
    relleno.setAttribute("aria-valuenow", c.porcentaje);
    relleno.setAttribute("aria-valuemin", "0");
    relleno.setAttribute("aria-valuemax", "100");
    relleno.style.width = c.porcentaje + "%";
    pista.append(relleno);
    li.append(fila, pista);
    lista.append(li);
  }
}

function dibujarUltimos(r) {
  const lista = $("ultimos");
  lista.replaceChildren();
  $("bloque-ultimos").hidden = r.ultimos.length === 0;
  for (const g of r.ultimos) {
    const li = crear("li", "list-group-item");
    const fila = crear("div", "fila-datos");
    const izquierda = crear("div");
    izquierda.append(crear("div", "fw-bold text-break", g.concepto), crear("div", "text-secondary small", g.categoria + " · " + fechaRelativa(g.fecha)));
    fila.append(izquierda, crear("div", "monto", soles(g.monto_centimos)));
    li.append(fila);
    lista.append(li);
  }
}

async function cargar() {
  raiz.classList.add("cargando");
  try {
    datos = await api("/api/resumen?mes=" + encodeURIComponent(mes));
    dibujarCabecera(datos);
    dibujarEstadisticas(datos);
    dibujarGrafico(datos);
    dibujarTabla(datos);
    dibujarCategorias(datos);
    dibujarUltimos(datos);
  } catch (e) {
    $("comparacion").textContent = e.message;
  } finally {
    raiz.classList.remove("cargando");
  }
}

$("mes-anterior").addEventListener("click", () => {
  mes = sumarMes(mes, -1);
  cargar();
});
$("mes-siguiente").addEventListener("click", () => {
  if (mes < MES_ACTUAL) {
    mes = sumarMes(mes, 1);
    cargar();
  }
});
$("actualizar").addEventListener("click", cargar);

new ResizeObserver(() => {
  const ancho = $("grafico").clientWidth;
  if (datos && ancho && Math.abs(ancho - anchoDibujado) >= 1) dibujarGrafico(datos);
}).observe($("grafico"));

cargar();
