/* Account modal: shows who you are and the one irreversible action there is. */

(() => {
  const openBtn = document.getElementById("account-btn");
  if (!openBtn) return;

  const modal = document.getElementById("account-modal");
  const emailEl = document.getElementById("account-email");
  const statusEl = document.getElementById("account-status");
  const form = document.getElementById("account-delete-form");
  const passwordEl = document.getElementById("account-password");
  const deleteBtn = document.getElementById("account-delete-btn");

  function setStatus(msg, tone) {
    statusEl.textContent = msg || "";
    statusEl.classList.toggle("hidden", !msg);
    statusEl.classList.toggle("text-err", tone === "err");
  }

  function reset() {
    form.classList.add("hidden");
    form.classList.remove("flex");
    passwordEl.value = "";
    deleteBtn.textContent = "Delete my account";
    setStatus("");
  }

  async function openModal() {
    reset();
    modal.classList.remove("hidden");
    modal.classList.add("flex");
    const r = await api("/auth/me");
    if (r.ok) emailEl.textContent = (await r.json()).email;
  }

  function closeModal() {
    modal.classList.add("hidden");
    modal.classList.remove("flex");
  }

  openBtn.addEventListener("click", openModal);
  document.getElementById("account-close").addEventListener("click", closeModal);
  modal.addEventListener("click", (e) => { if (e.target === modal) closeModal(); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !modal.classList.contains("hidden")) closeModal();
  });

  deleteBtn.addEventListener("click", async () => {
    if (form.classList.contains("hidden")) {
      // first click only asks for the password: nothing is destroyed by
      // clicking a button you meant to read
      form.classList.remove("hidden");
      form.classList.add("flex");
      deleteBtn.textContent = "Delete my account for good";
      passwordEl.focus();
      return;
    }
    if (!passwordEl.value) return setStatus("Enter your password to confirm.", "err");

    deleteBtn.disabled = true;
    setStatus("Deleting…");
    const r = await fetch("/auth/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: passwordEl.value }),
    });
    deleteBtn.disabled = false;
    if (r.ok) return (location.href = "/login");
    if (r.status === 401) return setStatus("That password doesn't match.", "err");
    const body = await r.json().catch(() => ({}));
    setStatus(body.detail || "Couldn't delete the account. Try again.", "err");
  });

  passwordEl.addEventListener("keydown", (e) => { if (e.key === "Enter") deleteBtn.click(); });
})();
