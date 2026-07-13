/* Shared shell: auth guard, credits badge, compare-slider component. */

async function api(path, options = {}) {
  const r = await fetch(path, options);
  if (r.status === 401) {
    location.href = "/login";
    throw new Error("not authenticated");
  }
  return r;
}

async function refreshCredits() {
  const r = await api("/credits");
  const { balance } = await r.json();
  document.getElementById("credits-badge").textContent = balance;
  return balance;
}

async function initShell() {
  const me = await (await api("/auth/me")).json();
  document.getElementById("topbar-email").textContent = me.email;
  document.getElementById("credits-badge").textContent = me.credits;
  document.getElementById("logout-btn").addEventListener("click", async () => {
    await fetch("/auth/logout", { method: "POST" });
    location.href = "/login";
  });
}

/* Before/after slider. Both images share the same aspect ratio (2x upscale),
   so absolute-positioned overlays line up exactly. Keyboard accessible via
   the invisible range input covering the stage. */
function initCompare(root, beforeUrl, afterUrl) {
  root.innerHTML = `
    <img alt="Enhanced result" draggable="false" data-cmp="after"
         class="block max-h-[62vh] w-full object-contain">
    <img alt="Original" draggable="false" data-cmp="before"
         class="absolute inset-0 h-full w-full object-contain">
    <div data-cmp="handle" class="pointer-events-none absolute inset-y-0 z-10 w-px bg-white/90" style="left:50%">
      <div class="absolute left-1/2 top-1/2 flex h-8 w-8 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border border-white/40 bg-black/70 text-xs text-white">&harr;</div>
    </div>
    <span class="pointer-events-none absolute left-3 top-3 z-10 rounded-full bg-black/60 px-2.5 py-1 text-xs text-white">Original</span>
    <span class="pointer-events-none absolute right-3 top-3 z-10 rounded-full bg-black/60 px-2.5 py-1 text-xs text-white">Enhanced</span>
    <input type="range" min="0" max="100" value="50" step="0.1"
           aria-label="Compare original and enhanced"
           class="absolute inset-0 z-20 h-full w-full cursor-ew-resize opacity-0">`;
  const before = root.querySelector('[data-cmp="before"]');
  const handle = root.querySelector('[data-cmp="handle"]');
  const range = root.querySelector("input[type=range]");
  root.querySelector('[data-cmp="after"]').src = afterUrl;
  before.src = beforeUrl;
  const set = (v) => {
    before.style.clipPath = `inset(0 ${100 - v}% 0 0)`;
    handle.style.left = `${v}%`;
  };
  range.addEventListener("input", () => set(parseFloat(range.value)));
  range.addEventListener("focus", () => root.classList.add("ring-2", "ring-accent"));
  range.addEventListener("blur", () => root.classList.remove("ring-2", "ring-accent"));
  set(50);
}

if (document.getElementById("credits-badge")) initShell();
