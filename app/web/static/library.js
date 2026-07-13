/* Library: grid of uploads, compare modal for enhanced ones. */

const grid = document.getElementById("grid");
const emptyState = document.getElementById("empty-state");
const modal = document.getElementById("modal");
const modalCompare = document.getElementById("modal-compare");
const modalMeta = document.getElementById("modal-meta");
const modalDownload = document.getElementById("modal-download");

async function loadLibrary() {
  const images = await (await api("/images")).json();
  emptyState.classList.toggle("hidden", images.length > 0);
  emptyState.classList.toggle("flex", images.length === 0);
  grid.innerHTML = "";
  for (const img of images) grid.appendChild(card(img));
}

function card(img) {
  const el = document.createElement(img.enhanced ? "button" : "div");
  el.className =
    "group relative block aspect-square overflow-hidden rounded-2xl border border-line bg-panel text-left";
  el.innerHTML = `
    <img alt="" loading="lazy" data-card="thumb"
         class="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105">
    <span data-card="status" class="absolute left-3 top-3 rounded-full px-2.5 py-1 text-xs"></span>
    <span data-card="dims" class="absolute bottom-3 left-3 rounded-full bg-black/60 px-2.5 py-1 font-mono text-xs text-white"></span>`;
  el.querySelector('[data-card="thumb"]').src = `/download/${encodeURIComponent(img.id)}/thumb`;
  const status = el.querySelector('[data-card="status"]');
  status.textContent = img.enhanced ? "Enhanced" : "Not enhanced";
  status.classList.add(...(img.enhanced ? ["bg-ok/15", "text-ok"] : ["bg-black/60", "text-mute"]));
  el.querySelector('[data-card="dims"]').textContent = `${img.width}×${img.height}`;
  if (img.enhanced) {
    el.addEventListener("click", () => openModal(img));
  }
  return el;
}

function openModal(img) {
  const id = encodeURIComponent(img.id);
  modalMeta.textContent = `${img.width}×${img.height} → ${img.width * 2}×${img.height * 2}`;
  modalDownload.href = `/download/${id}`;
  initCompare(modalCompare, `/download/${id}/original`, `/download/${id}`);
  modal.classList.remove("hidden");
  modal.classList.add("flex");
  modal.querySelector("input[type=range]").focus();
}

function closeModal() {
  modal.classList.add("hidden");
  modal.classList.remove("flex");
  modalCompare.innerHTML = "";
}

document.getElementById("modal-close").addEventListener("click", closeModal);
modal.addEventListener("click", (e) => { if (e.target === modal) closeModal(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });

loadLibrary();
