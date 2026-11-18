"use strict";
const el = id => document.getElementById(id);
let filters = {}, robots = [], after = null, busy = false, version = 0;
async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const details = await response.json().catch(() => ({}));
    throw new Error(details.message || `Request failed (${response.status})`);
  }
  return response.json();
}
function node(tag, text) {
  const item = document.createElement(tag);
  item.textContent = text;
  return item;
}
async function loadRobots(pagination = false) {
  const selected = el("robot").value;
  const page = await api("/v1/robots?" + new URLSearchParams({after: pagination ? after : ""}));
  const items = pagination ? robots.concat(page.items) : page.items;
  robots = [...new Map(items.map(r => [r.id, r])).values()];
  after = page.next_after;
  el("more").hidden = !after;
  el("robot").replaceChildren(new Option("All robots", ""), ...robots.map(r => new Option(r.id, r.id)));
  el("robot").value = robots.some(r => r.id === selected) ? selected : "";
}
async function refresh() {
  if (busy) return;
  busy = true;
  const snapshot = version;
  try {
    if (!robots.length || !el("robot").value && robots.length <= 100) await loadRobots();
    const visible = filters.robot_id ? robots.filter(r => r.id === filters.robot_id) : robots;
    const [detections, events, states] = await Promise.all([
      api("/v1/detections?" + new URLSearchParams({...filters, limit: "25"})),
      api("/v1/events?" + new URLSearchParams({...filters, kind: "alert", acknowledged: "false", limit: "25"})),
      Promise.all(visible.map(r => api(`/v1/robots/${encodeURIComponent(r.id)}/state`))),
    ]);
    if (snapshot !== version) return;
    el("detections").replaceChildren(...detections.items.map(d => {
      const row = node("tr", "");
      row.append(...[new Date(d.captured_at).toLocaleTimeString(), d.robot_id, d.class_label, `${(d.confidence * 100).toFixed(1)}%`].map(v => node("td", v)));
      return row;
    }));
    el("states").replaceChildren(...(states.length ? states.map(s =>
      node("li", `${s.robot_id} · ${s.platform} · v${s.state_version} · ${Object.entries(s.entity_count_by_class).map(([k, v]) => `${k}: ${v}`).join(", ") || "No tracked entities"}`)
    ) : [node("li", "No robots have submitted frames.")]));
    el("events").replaceChildren(...(events.items.length ? events.items.map(e => {
      const item = node("li", `${e.severity.toUpperCase()} · ${e.payload.rule_name} · ${e.robot_id} · ${new Date(e.occurred_at).toLocaleTimeString()}`);
      item.className = e.severity;
      const button = node("button", "Acknowledge");
      button.onclick = async () => {
        if (!el("actor").value.trim() || !el("token").value) {
          el("status").textContent = "Enter an operator name and token.";
          return;
        }
        button.disabled = true;
        try {
          await api(`/v1/events/${encodeURIComponent(e.id)}/acknowledge`, {
            method: "POST", headers: {"Content-Type": "application/json", "X-InGen-Operator-Token": el("token").value},
            body: JSON.stringify({actor: el("actor").value.trim()}),
          });
          item.remove();
          await refresh();
        } catch (error) { el("status").textContent = error.message; button.disabled = false; }
      };
      item.append(button);
      return item;
    }) : [node("li", "No unacknowledged alerts in this range.")]));
    el("status").textContent = `Live · updated ${new Date().toLocaleTimeString()}`;
  } catch (error) { el("status").textContent = error.message; }
  finally { busy = false; if (snapshot !== version) void refresh(); }
}
el("filters").onsubmit = event => {
  event.preventDefault();
  const next = {};
  if (el("robot").value) next.robot_id = el("robot").value;
  for (const key of ["start", "end"]) if (el(key).value) next[key] = new Date(el(key).value).toISOString();
  if (next.start && next.end && next.start >= next.end) {
    el("status").textContent = "From must be before To.";
    return;
  }
  filters = next; version++; void refresh();
};
el("filters").onreset = () => { filters = {}; version++; setTimeout(refresh, 0); };
el("more").onclick = async () => { try { await loadRobots(true); await refresh(); } catch (e) { el("status").textContent = e.message; } };
void refresh();
setInterval(refresh, 3000);
