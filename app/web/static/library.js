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
  // a <div>, not a <button>: the delete control nests inside it
  const el = document.createElement("div");
  el.className =
    "group relative block aspect-square overflow-hidden rounded-2xl border border-line bg-panel text-left";
  el.innerHTML = `
    <img alt="" loading="lazy" data-card="thumb"
         class="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105">
    <span data-card="status" class="absolute left-3 top-3 rounded-full px-2.5 py-1 text-xs"></span>
    <span data-card="dims" class="absolute bottom-3 left-3 rounded-full bg-black/60 px-2.5 py-1 font-mono text-xs text-white"></span>
    <button data-card="del" aria-label="Delete image"
            class="absolute right-3 top-3 hidden rounded-full bg-black/60 p-1.5 text-white/80 transition-colors hover:bg-err hover:text-white group-hover:block">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
    </button>`;
  el.querySelector('[data-card="thumb"]').src = `/download/${encodeURIComponent(img.id)}/thumb`;
  const status = el.querySelector('[data-card="status"]');
  status.textContent = img.enhanced ? "Enhanced" : "Not enhanced";
  status.classList.add(...(img.enhanced ? ["bg-ok/15", "text-ok"] : ["bg-black/60", "text-mute"]));
  el.querySelector('[data-card="dims"]').textContent = `${img.width}×${img.height}`;
  if (img.enhanced) {
    el.classList.add("cursor-pointer");
    el.tabIndex = 0;
    el.setAttribute("role", "button");
    el.addEventListener("click", () => openModal(img));
    el.addEventListener("keydown", (e) => { if (e.key === "Enter") openModal(img); });
  }

  const del = el.querySelector('[data-card="del"]');
  let armed = false;
  del.addEventListener("click", async (e) => {
    e.stopPropagation();
    if (!armed) {
      armed = true;
      del.replaceChildren("Delete?");
      del.classList.remove("hidden", "group-hover:block", "p-1.5");
      del.classList.add("block", "bg-err", "text-white", "px-2.5", "py-1", "text-xs");
      return;
    }
    del.disabled = true;
    const r = await api(`/images/${encodeURIComponent(img.id)}`, { method: "DELETE" });
    if (r.ok) {
      el.remove();
      if (!grid.children.length) loadLibrary(); // brings the empty state back
    } else {
      del.disabled = false;
      del.replaceChildren(r.status === 409 ? "Still processing…" : "Failed — retry?");
    }
  });
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
