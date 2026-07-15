/* Plan modal: monthly plans from /billing/plans, subscribe via Paddle.js
   overlay, then poll /credits until the webhook lands. */

(() => {
  const openBtn = document.getElementById("buy-credits-btn");
  if (!openBtn) return;

  const modal = document.getElementById("billing-modal");
  const plansBox = document.getElementById("billing-packs");
  const statusEl = document.getElementById("billing-status");
  const cancelBox = document.getElementById("billing-cancel");
  const cancelBtn = document.getElementById("billing-cancel-btn");
  const cancelNote = document.getElementById("billing-cancel-note");
  let cancelArmed = false;

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
    renderCancel();
  }

  function renderCancel() {
    cancelArmed = false;
    const { plan, cancels_at } = catalog.current;
    cancelBox.classList.toggle("hidden", !plan);
    if (!plan) return;
    if (cancels_at) {
      cancelBtn.classList.add("hidden");
      cancelNote.textContent =
        `Plan ends ${new Date(cancels_at).toLocaleDateString()} — remaining credits expire then.`;
      cancelNote.classList.remove("hidden");
    } else {
      cancelBtn.classList.remove("hidden");
      cancelBtn.classList.remove("text-err");
      cancelBtn.textContent = "Cancel subscription";
      cancelNote.classList.add("hidden");
    }
  }

  cancelBtn.addEventListener("click", async () => {
    if (!cancelArmed) {
      cancelArmed = true;
      cancelBtn.classList.add("text-err");
      cancelBtn.textContent =
        "You'll keep your credits until the period ends, then lose them. Click again to confirm.";
      return;
    }
    cancelBtn.disabled = true;
    const r = await api("/billing/cancel", { method: "POST" });
    cancelBtn.disabled = false;
    if (!r.ok) return setStatus("Couldn't cancel the subscription. Try again.", "err");
    catalog.current.cancels_at = (await r.json()).cancels_at;
    renderCancel();
    setStatus("Subscription canceled — no further charges.", "ok");
  });

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
      const { renews_at, cancels_at } = catalog.current;
      const when = cancels_at || renews_at;
      if (when) {
        btn.querySelector('[data-pl="credits"]').textContent +=
          ` · ${cancels_at ? "ends" : "renews"} ${new Date(when).toLocaleDateString()}`;
      }
    } else if (catalog.current.pending === plan.slug) {
      btn.disabled = true;
      btn.classList.add("opacity-60");
      const badge = btn.querySelector('[data-pl="badge"]');
      badge.textContent = "Starts next renewal";
      badge.classList.remove("hidden");
    } else if (catalog.current.cancels_at) {
      btn.disabled = true; // plan is ending; subscribe again once it does
      btn.classList.add("opacity-60");
    } else if (!catalog.current.plan) {
      btn.addEventListener("click", () => checkout(plan));
    } else {
      let armed = false; // switching bills money or reschedules it: confirm on 2nd click
      btn.addEventListener("click", () => (armed ? switchPlan(plan) : (armed = arm(plan, btn))));
    }
    return btn;
  }

  function isUpgrade(plan) {
    const cur = catalog.plans.find((p) => p.slug === catalog.current.plan);
    return !cur || plan.amount > cur.amount;
  }

  function arm(plan, btn) {
    btn.querySelector('[data-pl="name"]').textContent = `Switch to ${plan.name} — click to confirm`;
    setStatus(isUpgrade(plan)
      ? "You'll be charged the prorated difference for the rest of this period right away."
      : "No charge now — the new plan starts at your next renewal. You keep your current credits until then.");
    return true;
  }

  async function switchPlan(plan) {
    setStatus("Switching plans…");
    const r = await api("/billing/change", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan: plan.slug }),
    });
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      setStatus(body.detail || "Couldn't switch plans. Try again.", "err");
      load(); // un-arm the buttons
      return;
    }
    if ((await r.json()).status === "upgraded") {
      waitForCredits(); // the prorated charge's webhook lands in seconds
    } else {
      await load();
      setStatus(`Done — ${plan.name} starts at your next renewal.`, "ok");
    }
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
