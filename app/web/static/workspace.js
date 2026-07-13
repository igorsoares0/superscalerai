/* Workspace: upload -> preset -> job -> poll -> compare. */

const els = Object.fromEntries(
  ["stage-empty", "stage-work", "dropzone", "dropzone-label", "file-input", "upload-error",
   "work-title", "work-meta", "reset-btn", "preview-img", "scan-overlay", "compare-root",
   "controls", "cost-label", "enhance-btn", "job-error", "running-note", "running-label",
   "done-actions", "download-btn", "recent-grid", "recent-empty"]
    .map((id) => [id.replace(/-(\w)/g, (_, c) => c.toUpperCase()), document.getElementById(id)])
);

let current = null; // { imageId, width, height, objectUrl, preset }
let pollTimer = null;

/* mirrors app/services/credits.job_cost (2x scale) */
function estimateCost(w, h) {
  const edge = Math.max(w, h) * 2;
  return edge <= 1024 ? 1 : edge <= 2048 ? 2 : 4;
}

/* ---- upload ---- */

els.fileInput.addEventListener("change", () => {
  if (els.fileInput.files[0]) upload(els.fileInput.files[0]);
});
["dragover", "dragenter"].forEach((ev) =>
  els.dropzone.addEventListener(ev, (e) => { e.preventDefault(); els.dropzone.classList.add("border-accent/60"); })
);
["dragleave", "drop"].forEach((ev) =>
  els.dropzone.addEventListener(ev, (e) => { e.preventDefault(); els.dropzone.classList.remove("border-accent/60"); })
);
els.dropzone.addEventListener("drop", (e) => {
  const file = e.dataTransfer.files[0];
  if (file) upload(file);
});

async function upload(file) {
  els.uploadError.classList.add("hidden");
  if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
    return showUploadError("That file type isn't supported. Use JPG, PNG or WEBP.");
  }
  els.dropzoneLabel.textContent = "Uploading…";
  const form = new FormData();
  form.append("file", file);
  try {
    const r = await api("/images/upload", { method: "POST", body: form });
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      return showUploadError(body.detail || "Upload failed. Try again.");
    }
    const { id, width, height } = await r.json();
    current = { imageId: id, width, height, objectUrl: URL.createObjectURL(file), preset: "portrait" };
    enterReadyState();
  } finally {
    els.dropzoneLabel.textContent = "Drop an image here, or click to browse";
    els.fileInput.value = "";
  }
}

function showUploadError(msg) {
  els.uploadError.textContent = msg;
  els.uploadError.classList.remove("hidden");
}

/* ---- ready ---- */

function enterReadyState() {
  els.stageEmpty.classList.add("hidden");
  els.stageWork.classList.remove("hidden");
  els.previewImg.src = current.objectUrl;
  els.previewImg.classList.remove("hidden");
  els.compareRoot.classList.add("hidden");
  els.scanOverlay.classList.add("hidden");
  els.controls.classList.remove("hidden");
  els.runningNote.classList.add("hidden");
  els.runningNote.classList.remove("flex");
  els.doneActions.classList.add("hidden");
  els.doneActions.classList.remove("flex");
  els.jobError.classList.add("hidden");
  els.enhanceBtn.disabled = false;

  els.workTitle.textContent = "Ready to upscale";
  const cost = estimateCost(current.width, current.height);
  els.workMeta.textContent =
    `${current.width}×${current.height} → ${current.width * 2}×${current.height * 2}`;
  els.costLabel.textContent = `costs ${cost} credit${cost > 1 ? "s" : ""}`;
  selectPreset(current.preset);
}

document.querySelectorAll(".preset-chip").forEach((chip) =>
  chip.addEventListener("click", () => selectPreset(chip.dataset.preset))
);

function selectPreset(preset) {
  current.preset = preset;
  document.querySelectorAll(".preset-chip").forEach((chip) =>
    chip.setAttribute("aria-pressed", String(chip.dataset.preset === preset))
  );
}

els.resetBtn.addEventListener("click", () => {
  if (pollTimer) clearInterval(pollTimer);
  if (current?.objectUrl) URL.revokeObjectURL(current.objectUrl);
  current = null;
  els.stageWork.classList.add("hidden");
  els.stageEmpty.classList.remove("hidden");
});

/* ---- job ---- */

els.enhanceBtn.addEventListener("click", async () => {
  els.jobError.classList.add("hidden");
  els.enhanceBtn.disabled = true;
  const r = await api("/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ image_id: current.imageId, preset: current.preset }),
  });
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    els.jobError.textContent =
      r.status === 402
        ? "Not enough credits for this upscale."
        : body.detail || "Couldn't start the job. Try again.";
    els.jobError.classList.remove("hidden");
    els.enhanceBtn.disabled = false;
    return;
  }
  const job = await r.json();
  refreshCredits();
  enterRunningState();
  pollTimer = setInterval(() => poll(job.id), 2500);
});

function enterRunningState() {
  els.workTitle.textContent = "Enhancing";
  els.controls.classList.add("hidden");
  els.runningNote.classList.remove("hidden");
  els.runningNote.classList.add("flex");
  els.scanOverlay.classList.remove("hidden");
}

async function poll(jobId) {
  const r = await api(`/jobs/${jobId}`);
  if (!r.ok) return;
  const job = await r.json();
  if (job.status === "completed") {
    clearInterval(pollTimer);
    enterDoneState();
  } else if (job.status === "failed") {
    clearInterval(pollTimer);
    enterFailedState(job.error);
  }
}

function enterDoneState() {
  els.workTitle.textContent = "Done — compare the result";
  els.scanOverlay.classList.add("hidden");
  els.runningNote.classList.add("hidden");
  els.runningNote.classList.remove("flex");
  els.previewImg.classList.add("hidden");
  els.compareRoot.classList.remove("hidden");
  initCompare(els.compareRoot, current.objectUrl, `/download/${current.imageId}?t=${Date.now()}`);
  els.downloadBtn.href = `/download/${current.imageId}`;
  els.doneActions.classList.remove("hidden");
  els.doneActions.classList.add("flex");
  refreshCredits();
  loadRecent();
}

function enterFailedState(message) {
  els.workTitle.textContent = "Enhancement failed";
  els.scanOverlay.classList.add("hidden");
  els.runningNote.classList.add("hidden");
  els.runningNote.classList.remove("flex");
  els.controls.classList.remove("hidden");
  els.enhanceBtn.disabled = false;
  els.jobError.textContent = `${message || "Something went wrong."} Your credits were refunded — you can try again.`;
  els.jobError.classList.remove("hidden");
  refreshCredits();
}

/* ---- recent strip ---- */

async function loadRecent() {
  const images = await (await api("/images")).json();
  const enhanced = images.filter((i) => i.enhanced).slice(0, 5);
  els.recentGrid.innerHTML = "";
  els.recentEmpty.classList.toggle("hidden", enhanced.length > 0);
  for (const img of enhanced) {
    const a = document.createElement("a");
    a.href = "/library";
    a.className =
      "group relative block aspect-square overflow-hidden rounded-xl border border-line bg-panel";
    const thumb = document.createElement("img");
    thumb.src = `/download/${encodeURIComponent(img.id)}/thumb`;
    thumb.alt = "Enhanced image";
    thumb.loading = "lazy";
    thumb.className =
      "h-full w-full object-cover transition-transform duration-300 group-hover:scale-105";
    a.appendChild(thumb);
    els.recentGrid.appendChild(a);
  }
}

loadRecent();
