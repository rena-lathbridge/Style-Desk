/* The Style Desk — front end. No framework, no build step. */

const SID = (() => {
  let s = sessionStorage.getItem("sid");
  if (!s) { s = Math.random().toString(36).slice(2, 10); sessionStorage.setItem("sid", s); }
  return s;
})();

const BUDGET = 400000;
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

let PROFILE = null;

/* ---------- tabs ---------- */

document.querySelectorAll("nav.tabs button").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("nav.tabs button").forEach((b) =>
      b.setAttribute("aria-selected", String(b === btn)));
    document.querySelectorAll(".panel").forEach((p) =>
      p.classList.toggle("active", p.id === btn.dataset.tab));
  });
});

/* ---------- file pickers ---------- */

function wireZone(zoneId, inputId, thumbsId, multiple, urlSinkId) {
  const zone = $(zoneId), input = $(inputId), thumbs = thumbsId ? $(thumbsId) : null;
  zone.addEventListener("click", () => input.click());
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("over"));
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    zone.classList.remove("over");

    // Dragging a file gives us bytes; dragging an image out of another tab
    // gives us only its URL, so collect that into the links box instead.
    if (e.dataTransfer.files && e.dataTransfer.files.length) {
      input.files = e.dataTransfer.files;
      input.dispatchEvent(new Event("change"));
      return;
    }
    const sink = urlSinkId ? $(urlSinkId) : null;
    if (!sink) return;
    const dropped = (e.dataTransfer.getData("text/uri-list") ||
                     e.dataTransfer.getData("text/plain") || "").trim();
    if (!dropped) return;
    const lines = sink.value.split("\n").map((x) => x.trim()).filter(Boolean);
    if (!lines.includes(dropped)) lines.push(dropped);
    sink.value = lines.join("\n");
    sink.dispatchEvent(new Event("input"));
  });
  input.addEventListener("change", () => {
    if (!thumbs) return;
    thumbs.innerHTML = "";
    [...input.files].slice(0, multiple ? 6 : 1).forEach((f) => {
      const img = document.createElement("img");
      img.src = URL.createObjectURL(f);
      thumbs.appendChild(img);
    });
  });
}

wireZone("inspo-zone", "inspo-files", "inspo-thumbs", true, "inspo-urls");
wireZone("ward-zone", "ward-files", null, true);
wireZone("fit-zone", "fit-file", "fit-thumbs", false);

/* ---------- network ---------- */

function working(target, label) {
  $(target).innerHTML =
    `<div class="working"><span class="spinner"></span><span>${esc(label)}</span></div>`;
}

function problem(target, message, kind = "block") {
  $(target).innerHTML =
    `<div class="notice ${kind}"><strong>${kind === "block" ? "Request refused" : "Heads up"}</strong>${esc(message)}</div>`;
}

async function send(url, options, target, label) {
  working(target, label);
  try {
    const res = await fetch(url, options);
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      problem(target, body.detail || body.error || `Something went wrong (${res.status}).`);
      await refresh();
      return null;
    }
    if (body.receipt) paintReceipt(body.receipt);
    return body;
  } catch (err) {
    problem(target, "Could not reach the server. Is it still running?");
    return null;
  }
}

/* ---------- 01: teach ---------- */

$("inspo-go").addEventListener("click", async () => {
  const files = $("inspo-files").files;
  const urls = $("inspo-urls").value.trim();
  if (!files.length && !urls) {
    return problem("teach-out", "Add at least one inspiration image, or paste a link.");
  }

  const form = new FormData();
  [...files].slice(0, 6).forEach((f) => form.append("files", f));
  form.append("urls", urls);
  form.append("note", $("inspo-note").value);

  const body = await send(`/api/profile/${SID}`, { method: "POST", body: form },
    "teach-out", "Reading the photos for a pattern…");
  if (!body) return;

  PROFILE = body.profile;
  paintProfile(body.profile);
});

function paintProfile(p) {
  const rows = p.principles.map((pr) => `
    <div class="principle" data-pid="${esc(pr.id)}">
      <div class="pid">${esc(pr.id)}</div>
      <div>
        <div class="dim">${esc(pr.dimension)}<span class="conf ${pr.confidence === "low" ? "low" : ""}">${esc(pr.confidence)} confidence</span></div>
        <div class="rule" data-field="rule">${esc(pr.rule)}</div>
        <div class="ev">${esc(pr.evidence)}</div>
      </div>
    </div>`).join("");

  $("teach-out").innerHTML = `
    <h3 class="profile-head">${esc(p.headline)}</h3>
    <div id="principle-rows">${rows}</div>
    <p class="lede" style="margin-top:22px">Palette</p>
    <div class="chips">${p.palette.map((c) => `<span class="chip">${esc(c)}</span>`).join("")}</div>
    <p class="lede" style="margin-top:22px">This look breaks when</p>
    <div class="chips">${p.avoid.map((c) => `<span class="chip">${esc(c)}</span>`).join("")}</div>
    <p style="margin-top:26px">
      <button class="ghost" id="edit-btn">Disagree? Edit these</button>
      <button class="ghost" id="save-btn" style="display:none">Save changes</button>
    </p>`;

  $("edit-btn").addEventListener("click", () => {
    document.querySelectorAll('#principle-rows .rule').forEach((el) => {
      el.setAttribute("contenteditable", "true");
    });
    $("edit-btn").style.display = "none";
    $("save-btn").style.display = "inline-block";
    document.querySelector("#principle-rows .rule")?.focus();
  });

  $("save-btn").addEventListener("click", async () => {
    document.querySelectorAll("#principle-rows .principle").forEach((row, i) => {
      PROFILE.principles[i].rule = row.querySelector(".rule").innerText.trim();
    });
    document.querySelectorAll('#principle-rows .rule').forEach((el) =>
      el.removeAttribute("contenteditable"));
    await fetch(`/api/profile/${SID}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        headline: PROFILE.headline, principles: PROFILE.principles,
        palette: PROFILE.palette, avoid: PROFILE.avoid,
      }),
    });
    $("save-btn").style.display = "none";
    $("edit-btn").style.display = "inline-block";
  });
}

/* ---------- 02: build ---------- */

$("seed-btn").addEventListener("click", async () => {
  const res = await fetch(`/api/wardrobe/seed/${SID}`, { method: "POST" });
  const body = await res.json();
  paintWardrobe(body.wardrobe);
});

$("ward-files").addEventListener("change", async () => {
  const files = $("ward-files").files;
  if (!files.length) return;
  const form = new FormData();
  [...files].forEach((f) => form.append("files", f));
  const body = await send(`/api/wardrobe/${SID}`, { method: "POST", body: form },
    "build-out", `Cataloging ${files.length} item${files.length > 1 ? "s" : ""}…`);
  if (!body) return;
  paintWardrobe(body.wardrobe);
  $("build-out").innerHTML =
    `<p class="lede">Added ${body.added.length} item${body.added.length > 1 ? "s" : ""}. Build outfits when you are ready.</p>`;
});

$("outfit-go").addEventListener("click", async () => {
  const body = await send(`/api/outfits/${SID}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ occasion: $("occasion").value }),
  }, "build-out", "Putting outfits together…");
  if (!body) return;

  const names = {};
  document.querySelectorAll("#wardrobe-list .w").forEach((el) => {
    names[el.dataset.gid] = el.dataset.name;
  });
  const ruleFor = (pid) =>
    (PROFILE?.principles || []).find((p) => p.id === pid)?.rule || pid;

  $("build-out").innerHTML = body.outfits.outfits.map((o) => `
    <div class="outfit">
      <h3>${esc(o.title)}</h3>
      <ul>${o.pieces.map((pc) =>
        `<li>${esc(names[pc.garment_id] || pc.garment_id)} <span class="role">&mdash; ${esc(pc.role)}</span></li>`).join("")}</ul>
      <div class="cites">${o.principles_used.map((pid) =>
        `<span class="cite" title="${esc(ruleFor(pid))}">${esc(pid)}</span>`).join("")}</div>
      <p class="why">${esc(o.why_it_works)}</p>
      <p class="watch">${esc(o.watch_out_for)}</p>
    </div>`).join("") +
    `<div class="lesson"><span class="tag">Take this with you</span>${esc(body.outfits.lesson)}</div>`;
});

/* ---------- 03: debug ---------- */

$("fit-go").addEventListener("click", async () => {
  const file = $("fit-file").files[0];
  if (!file) return problem("debug-out", "Add a photo of the outfit first.");
  const form = new FormData();
  form.append("file", file);
  form.append("complaint", $("complaint").value);

  const body = await send(`/api/critique/${SID}`, { method: "POST", body: form },
    "debug-out", "Looking at the outfit…");
  if (!body) return;

  const c = body.critique;
  const ruleFor = (pid) =>
    (PROFILE?.principles || []).find((p) => p.id === pid)?.rule || pid;

  $("debug-out").innerHTML = `
    <p class="why" style="margin-top:26px">${esc(c.reading)}</p>
    <div class="verdict">
      <div><h4>Working</h4><ul>${c.working.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div>
      <div><h4>Not working</h4><ul>${c.not_working.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div>
    </div>
    <h4 style="font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:var(--muted)">Try this</h4>
    ${c.fixes.map((f) => `
      <div class="fix">
        <div>${esc(f.change)}<br><span class="cite" title="${esc(ruleFor(f.principle_id))}">${esc(f.principle_id)}</span></div>
        <div class="effort">${esc(f.effort)}</div>
      </div>`).join("")}
    <div class="lesson"><span class="tag">Remember</span>${esc(c.lesson)}</div>`;
});

/* ---------- sidebar ---------- */

function paintReceipt(r) {
  const t = r.totals;
  $("receipt").innerHTML = `
    <div class="stat"><span>Model calls</span><span class="v">${t.calls}</span></div>
    <div class="stat"><span>Served from cache</span><span class="v">${t.cache_hits}</span></div>
    <div class="stat"><span>Input tokens</span><span class="v">${t.input_tokens.toLocaleString()}</span></div>
    <div class="stat"><span>&nbsp;&nbsp;of which cached</span><span class="v">${t.cached_tokens.toLocaleString()}</span></div>
    <div class="stat"><span>Output tokens</span><span class="v">${t.output_tokens.toLocaleString()}</span></div>
    <div class="stat"><span>&nbsp;&nbsp;of which reasoning</span><span class="v">${t.reasoning_tokens.toLocaleString()}</span></div>
    <div class="stat total"><span>Cost this session</span><span class="v">$${t.cost_usd.toFixed(6)}</span></div>`;

  const used = BUDGET - t.tokens_remaining;
  $("budget-bar").style.width = `${Math.min(100, (used / BUDGET) * 100).toFixed(1)}%`;

  $("call-list").innerHTML = r.calls.map((c) => `
    <div class="row ${c.cache_hit ? "hit" : ""}">
      <span>${esc(c.agent)}${c.cache_hit ? " (cached)" : ""}</span>
      <span>${c.cache_hit ? "free" : `$${c.cost_usd.toFixed(5)}`}</span>
    </div>`).join("");

  if (r.safety_events.length) {
    $("safety-card").style.display = "block";
    $("safety-list").innerHTML = r.safety_events.map((e) => `
      <div class="notice caught" style="margin:0 0 10px">
        <strong>${esc(e.kind.replace("_", " "))}</strong>
        ${esc(e.detail)}<br><em>${esc(e.action)}</em>
      </div>`).join("");
  }
}

function paintWardrobe(items) {
  if (!items.length) return;
  $("wardrobe-list").innerHTML = items.map((g) =>
    `<div class="w" data-gid="${esc(g.id)}" data-name="${esc(g.name)}"><b>${esc(g.id)}</b><span>${esc(g.name)}</span></div>`).join("");
}

async function refresh() {
  const res = await fetch(`/api/state/${SID}`);
  if (!res.ok) return;
  const s = await res.json();
  if (s.profile) { PROFILE = s.profile; paintProfile(s.profile); }
  paintWardrobe(s.wardrobe);
  paintReceipt(s.receipt);
}

refresh();
