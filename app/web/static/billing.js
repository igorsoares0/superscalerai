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
  let resumeMode = false; // the cancel button turns into "Resume" once scheduled

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
    if (!catalog.email_verified) lockPlansUntilConfirmed();
  }

  /* Buying while unconfirmed leaves a charged card on an account that can't
     upload. Canceling stays clickable on purpose: whoever already has a plan
     must always be able to stop the charges. */
  function lockPlansUntilConfirmed() {
    for (const btn of plansBox.querySelectorAll("button")) {
      btn.disabled = true;
      btn.classList.add("opacity-60");
    }
    setStatus("Confirm your email before subscribing — the link is in your inbox.", "err");
  }

  function renderCancel() {
    cancelArmed = false;
    const { plan, cancels_at } = catalog.current;
    cancelBox.classList.toggle("hidden", !plan);
    if (!plan) return;
    resumeMode = Boolean(cancels_at);
    cancelBtn.classList.remove("hidden", "text-err");
    cancelBtn.textContent = resumeMode ? "Resume subscription" : "Cancel subscription";
    cancelNote.classList.toggle("hidden", !resumeMode);
    if (resumeMode) {
      cancelNote.textContent =
        `Plan ends ${new Date(cancels_at).toLocaleDateString()} — remaining credits expire then.`;
    }
  }

  async function resumeSubscription() {
    cancelBtn.disabled = true;
    const r = await api("/billing/resume", { method: "POST" });
    cancelBtn.disabled = false;
    if (!r.ok) return setStatus("Couldn't resume the subscription. Try again.", "err");
    await load();
    setStatus("Subscription resumed — it renews as usual.", "ok");
  }

  cancelBtn.addEventListener("click", async () => {
    // no two-click confirm here: undoing a mistake shouldn't need convincing
    if (resumeMode) return resumeSubscription();
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
    // scheduled a downgrade and had second thoughts: the plan you're on is the
    // way back, so its button has to stay clickable
    const undoPending = isCurrent && Boolean(catalog.current.pending);
    const btn = document.createElement("button");
    btn.disabled = isCurrent && !undoPending;
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
      if (undoPending) {
        btn.classList.add("hover:border-accent/60");
        let armed = false;
        btn.addEventListener("click", () => (armed ? switchPlan(plan) : (armed = armKeep(plan, btn))));
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
      ? `You'll be charged the prorated difference for the rest of this period right away, and get the matching share of the extra credits now. Your full ${plan.credits} land at the next renewal.`
      : "No charge now — the new plan starts at your next renewal. You keep your current credits until then.");
    return true;
  }

  function armKeep(plan, btn) {
    const pending = catalog.plans.find((p) => p.slug === catalog.current.pending);
    btn.querySelector('[data-pl="name"]').textContent = `Keep ${plan.name} — click to confirm`;
    setStatus(
      `Cancels the switch to ${pending ? pending.name : catalog.current.pending}. ` +
      `Nothing is charged and you stay on ${plan.name}.`);
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
    const status = (await r.json()).status;
    if (status === "upgraded") {
      waitForCredits(); // the prorated charge's webhook lands in seconds
    } else {
      await load();
      setStatus(
        status === "kept"
          ? `Done — you stay on ${plan.name}.`
          : `Done — ${plan.name} starts at your next renewal.`,
        "ok");
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
    if (!catalog.email_verified) return lockPlansUntilConfirmed();
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
