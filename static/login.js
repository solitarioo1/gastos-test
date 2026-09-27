const raiz = $("acceso-tarjeta");
const tabs = $("acceso-tabs");
const tabEntrar = $("tab-entrar");
const tabRegistro = $("tab-registro");
const panelEntrar = $("panel-entrar");
const panelRegistro = $("panel-registro");
const riel = $("acceso-riel");
const paneles = document.querySelector(".acceso-paneles");
const mensaje = $("acceso-mensaje");
const botonCambiar = $("btn-cambiar-modo");

function mostrar(cual) {
  const esRegistro = cual === "registro";
  raiz.dataset.activo = cual;
  tabs.dataset.activo = cual;
  tabEntrar.setAttribute("aria-selected", esRegistro ? "false" : "true");
  tabRegistro.setAttribute("aria-selected", esRegistro ? "true" : "false");
  panelEntrar.toggleAttribute("inert", esRegistro);
  panelRegistro.toggleAttribute("inert", !esRegistro);
  botonCambiar.textContent = esRegistro ? "Entrar" : "Registrarse";

  // En celular (el panel de color no se desliza) no hay nada más que mover.
  // En pantallas anchas, el riel (formularios) y el panel de color se miden en
  // píxeles reales y se corren exactamente esa distancia: nada de "%", que en un
  // riel más ancho que su caja se presta a confusión (ver nota en style.css).
  riel.style.transform = esRegistro ? `translateX(-${paneles.clientWidth}px)` : "translateX(0)";
  // El panel de color arranca (CSS) cubriendo la mitad derecha; para "registro" se
  // corre a la izquierda exactamente su propio ancho.
  mensaje.style.transform = esRegistro ? `translateX(-${mensaje.clientWidth}px)` : "translateX(0)";

  if (esRegistro) $("volver-entrar").focus();
  else $("usuario").focus();
}

tabEntrar.addEventListener("click", () => mostrar("entrar"));
tabRegistro.addEventListener("click", () => mostrar("registro"));
botonCambiar.addEventListener("click", () => mostrar(raiz.dataset.activo === "registro" ? "entrar" : "registro"));
$("volver-entrar").addEventListener("click", () => mostrar("entrar"));

let anchoAnterior = window.innerWidth;
window.addEventListener("resize", () => {
  // si la ventana cambia de tamaño (o gira el celular), recalcula sin animación
  if (window.innerWidth === anchoAnterior) return;
  anchoAnterior = window.innerWidth;
  const activo = raiz.dataset.activo;
  riel.style.transition = mensaje.style.transition = "none";
  mostrar(activo);
  requestAnimationFrame(() => {
    riel.style.transition = mensaje.style.transition = "";
  });
});
