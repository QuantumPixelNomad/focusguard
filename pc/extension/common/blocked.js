"use strict";
const params = new URLSearchParams(location.search);
const set = (id, text) => { document.getElementById(id).textContent = text || ""; };
set("reason", params.get("reason") || "This page is blocked right now.");
set("title", params.get("title") ? "Video: " + params.get("title") : "");
const until = Number(params.get("until"));
if (until) {
  const d = new Date(until * 1000);
  set("until", "Blocking ends " + d.toLocaleString([], { weekday: "long", hour: "2-digit", minute: "2-digit" }) + ".");
}
set("url", params.get("url"));
