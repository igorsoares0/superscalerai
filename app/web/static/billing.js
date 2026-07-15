/* Plan modal: monthly plans from /billing/plans, subscribe via Paddle.js
   overlay, then poll /credits until the webhook lands. */

(() => {
  const openBtn = document.getElementById("buy-credits-btn");
  if (!openBtn) return;

  const modal = document.getElementById("billing-modal");
  const plansBox = document.getElementById("billing-packs");
  const statusEl = document.getElementById("billing-status");

  let catalog = null; // { environment, client_token, plans, current }
  let me = null; // { id, email }
  let paddleReady = false;
  let confirmTimer = null;

  function setStatus(msg, tone) {
    statusEl.textContent = msg || "";
    statusEl.classList.toggle("hidden", !msg);
    statusEl.classList.toggle("text-err", tone === "err");
    statusEl.classList.toggle("text-ok", tone === "ok");
    statusEl.classList.toggle("text-mute", !tone);
  }

  function fmtPrice(amount, currency) {
    return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(amount / 100);
  }

  /* ---- modal ---- */

  function openModal() {
    modal.classList.remove("hidden");
    modal.classList.add("flex");
    setStatus("");
    load(); // refetch so the current-plan badge is never stale
  }

  function closeModal() {
    modal.classList.add("hidden");
    modal.classList.remove("flex");
    if (confirmTimer) clearInterval(confirmTimer);
  }

  openBtn.addEventListener("click", openModal);
  document.getElementById("billing-close").addEventListener("click", closeModal);
  modal.addEventListener("click", (e) => { if (e.target === modal) closeModal(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });

  /* ---- plans ---- */

  async function load() {
    if (!catalog) setStatus("Loading plans…");
    const [plansRes, meRes] = await Promise.all([api("/billing/plans"), api("/auth/me")]);
    if (!plansRes.ok || !meRes.ok) return setStatus("Couldn't load plans. Try again.", "err");
    catalog = await plansRes.json();
    me = await meRes.json();
    setStatus("");
    plansBox.innerHTML = "";
    for (const plan of catalog.plans) plansBox.appendChild(planButton(plan));
  }

  function planButton(plan) {
    const isCurrent = catalog.current.plan === plan.slug;
    const btn = document.createElement("button");
    btn.disabled = isCurrent;
    btn.className =
      "flex items-center justify-between rounded-xl border px-4 py-3 text-left transition-colors " +
      (isCurrent
        ? "border-accent/60 bg-accent/10"
        : "border-line bg-raise hover:border-accent/60");
    btn.innerHTML = `
      <span>
        <span class="flex items-center gap-2">
          <span data-pl="name" class="text-sm font-medium"></span>
          <span data-pl="badge" class="hidden rounded-full bg-accent/20 px-2 py-0.5 text-xs text-accent">Current plan</span>
        </span>
        <span data-pl="credits" class="block font-mono text-xs text-mute"></span>
      </span>
      <span data-pl="price" class="font-mono text-sm text-accent"></span>`;
    btn.querySelector('[data-pl="name"]').textContent = plan.name;
    btn.querySelector('[data-pl="credits"]').textContent = `${plan.credits} credits / month`;
    btn.querySelector('[data-pl="price"]').textContent =
      `${fmtPrice(plan.amount, plan.currency)}/mo`;
    if (isCurrent) {
      btn.querySelector('[data-pl="badge"]').classList.remove("hidden");
      const renews = catalog.current.renews_at;
      if (renews) {
        btn.querySelector('[data-pl="credits"]').textContent +=
          ` · renews ${new Date(renews).toLocaleDateString()}`;
      }
    } else {
      btn.addEventListener("click", () => checkout(plan));
    }
    return btn;
  }

  /* ---- checkout ---- */

  function initPaddle() {
    if (paddleReady) return true;
    if (typeof Paddle === "undefined") return false;
    if (catalog.environment === "sandbox") Paddle.Environment.set("sandbox");
    Paddle.Initialize({
      token: catalog.client_token,
      eventCallback(event) {
        if (event.name === "checkout.completed") {
          Paddle.Checkout.close();
          waitForCredits();
        }
      },
    });
    paddleReady = true;
    return true;
  }

  function checkout(plan) {
    if (!initPaddle()) return setStatus("Payment script is still loading — try again in a second.", "err");
    if (!catalog.client_token) return setStatus("Payments aren't configured on this server.", "err");
    Paddle.Checkout.open({
      items: [{ priceId: plan.price_id, quantity: 1 }],
      customData: { app: "superscaler", user_id: me.id },
      customer: { email: me.email },
    });
  }

  /* The webhook resets the balance moments after checkout; poll until it
     moves so the user sees the new plan without refreshing. */
  async function waitForCredits() {
    setStatus("Payment received — activating your plan…");
    const before = await balance();
    let tries = 0;
    confirmTimer = setInterval(async () => {
      const now = await balance();
      if (now !== null && before !== null && now !== before) {
        clearInterval(confirmTimer);
        refreshCredits();
        load();
        setStatus(`Done! Your balance is now ${now} credits.`, "ok");
      } else if (++tries >= 15) {
        clearInterval(confirmTimer);
        refreshCredits();
        load();
        setStatus("Payment confirmed. Your plan can take a minute to activate.", "ok");
      }
    }, 2000);
  }

  async function balance() {
    const r = await api("/credits");
    if (!r.ok) return null;
    return (await r.json()).balance;
  }
})();
