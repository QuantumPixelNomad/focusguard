// FocusGuard browser extension.
// Asks the local FocusGuard service what is blocked right now, then:
//  * sends tabs on blocked sites to the "blocked" page, and
//  * on YouTube, looks up each video's category and blocks the ones that are off topic.
"use strict";

const api = globalThis.browser ?? globalThis.chrome;
const SERVICE = "http://127.0.0.1:47613";
const POLICY_MAX_AGE_MS = 10000;
const YT_HOSTS = ["youtube.com", "youtu.be", "youtube-nocookie.com"];

let policy = null;
let policyAt = 0;
let serviceReachable = false;
const videoCache = new Map(); // video id -> {category, title, text}

function browserName() {
  const ua = navigator.userAgent;
  if (ua.includes("Firefox/")) return "firefox";
  const brands = (navigator.userAgentData?.brands ?? []).map((b) => b.brand);
  if (brands.includes("Brave") || navigator.brave) return "brave";
  if (brands.includes("Microsoft Edge") || ua.includes("Edg/")) return "edge";
  if (brands.includes("Opera") || ua.includes("OPR/")) return "opera";
  if (brands.includes("Google Chrome")) return "chrome";
  return "chromium";
}

async function loadPolicy(force = false) {
  if (!force && policy && Date.now() - policyAt < POLICY_MAX_AGE_MS) return policy;
  try {
    const resp = await fetch(SERVICE + "/heartbeat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ browser: browserName() }),
      cache: "no-store",
    });
    if (!resp.ok) throw new Error("service answered " + resp.status);
    policy = await resp.json();
    policyAt = Date.now();
    serviceReachable = true;
    api.storage.local.set({ policy });
  } catch (err) {
    serviceReachable = false;
    if (!policy) {
      const stored = await api.storage.local.get("policy");
      policy = stored.policy ?? null;
    }
    // The service is down. Keep enforcing the last known block until its end time.
    if (policy && policy.active && policy.until && Date.now() / 1000 > policy.until) {
      policy = { ...policy, active: false, blocked_domains: [] };
    }
    policyAt = Date.now();
  }
  return policy;
}

function hostMatches(host, domain) {
  return host === domain || host.endsWith("." + domain);
}

function matchList(host, list) {
  return (list ?? []).find((d) => hostMatches(host, d)) ?? null;
}

function youtubeVideoId(url) {
  const host = url.hostname.replace(/^(www|m|music)\./, "");
  if (host === "youtu.be") return url.pathname.slice(1).split("/")[0] || null;
  if (url.pathname === "/watch") return url.searchParams.get("v");
  const m = url.pathname.match(/^\/(shorts|live|embed|v)\/([\w-]{6,})/);
  return m ? m[2] : null;
}

function decodeText(s) {
  return s
    .replace(/\\u0026/g, "&")
    .replace(/\\u([0-9a-fA-F]{4})/g, (_, h) => String.fromCharCode(parseInt(h, 16)))
    .replace(/\\"/g, '"')
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">");
}

// Pull the category, title, channel and tags out of a YouTube watch page.
function parseWatchPage(html) {
  const pick = (...patterns) => {
    for (const re of patterns) {
      const m = html.match(re);
      if (m && m[1]) return decodeText(m[1]).trim();
    }
    return "";
  };
  const category = pick(/"category":"((?:[^"\\]|\\.)+)"/, /itemprop="genre"\s+content="([^"]+)"/);
  const title = pick(/<meta\s+name="title"\s+content="([^"]*)"/, /<meta\s+property="og:title"\s+content="([^"]*)"/,
    /<title>([^<]*)<\/title>/);
  const channel = pick(/"ownerChannelName":"((?:[^"\\]|\\.)+)"/, /<link\s+itemprop="name"\s+content="([^"]*)"/);
  // The video's own tags live in the player data; the keywords meta tag is often YouTube's generic text.
  const keywords = pick(/"videoDetails":\{[^]*?"keywords":\[((?:"(?:[^"\\]|\\.)*",?)*)\]/,
    /<meta\s+name="keywords"\s+content="([^"]*)"/);
  return { category, title, channel, keywords };
}

async function videoInfo(id) {
  if (videoCache.has(id)) return videoCache.get(id);
  let info = { category: "", title: "", channel: "", keywords: "" };
  try {
    const resp = await fetch("https://www.youtube.com/watch?v=" + encodeURIComponent(id), { credentials: "include" });
    if (resp.ok) info = parseWatchPage(await resp.text());
  } catch (err) {
    // Leave the category unknown; the "unknown" setting decides.
  }
  if (info.category || info.title) {
    if (videoCache.size > 500) videoCache.delete(videoCache.keys().next().value);
    videoCache.set(id, info);
  }
  return info;
}

// Returns a reason string if the video must be blocked, otherwise null.
function judgeVideo(info, yt) {
  const text = [info.title, info.channel, info.keywords].join(" \n ").toLowerCase();
  const blockWord = (yt.block_keywords ?? []).find((k) => k && text.includes(k));
  if (blockWord) return `it matches your block keyword "${blockWord}"`;
  const allowWord = (yt.allow_keywords ?? []).find((k) => k && text.includes(k));
  if (allowWord) return null;
  if (info.category) {
    if ((yt.allowed_categories ?? []).includes(info.category)) return null;
    return `its YouTube category is "${info.category}"`;
  }
  return yt.unknown === "allow" ? null : "its category could not be determined";
}

async function decide(rawUrl) {
  let url;
  try {
    url = new URL(rawUrl);
  } catch (err) {
    return null;
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") return null;
  const p = await loadPolicy();
  if (!p || !p.active) return null;
  const host = url.hostname.toLowerCase();

  if (matchList(host, YT_HOSTS)) {
    const yt = p.youtube ?? {};
    if (yt.mode === "allow") return null;
    if (yt.mode === "block") return { reason: "YouTube is blocked right now." };
    if (yt.block_shorts && url.pathname.startsWith("/shorts")) return { reason: "YouTube Shorts are blocked right now." };
    const id = youtubeVideoId(url);
    if (!id) return null; // home page, search, channels, playlists
    const info = await videoInfo(id);
    const why = judgeVideo(info, yt);
    return why ? { reason: `This video is blocked because ${why}.`, title: info.title } : null;
  }

  if (matchList(host, p.exceptions)) return null;
  const hit = matchList(host, p.blocked_domains);
  return hit ? { reason: `${hit} is on your block list.` } : null;
}

async function checkTab(tabId, rawUrl) {
  if (!rawUrl || rawUrl.startsWith(api.runtime.getURL(""))) return;
  const verdict = await decide(rawUrl);
  if (!verdict) return;
  try {
    const tab = await api.tabs.get(tabId);
    if (tab.url !== rawUrl && tab.pendingUrl !== rawUrl) return; // the tab moved on while we looked
    const page = new URL(api.runtime.getURL("blocked.html"));
    page.searchParams.set("url", rawUrl);
    page.searchParams.set("reason", verdict.reason);
    if (verdict.title) page.searchParams.set("title", verdict.title);
    if (policy?.until) page.searchParams.set("until", String(policy.until));
    await api.tabs.update(tabId, { url: page.toString() });
  } catch (err) {
    // The tab was closed.
  }
}

async function sweep() {
  await loadPolicy(true);
  if (!policy || !policy.active) return;
  const tabs = await api.tabs.query({});
  for (const tab of tabs) {
    if (tab.id !== undefined && tab.url) checkTab(tab.id, tab.url);
  }
}

api.tabs.onUpdated.addListener((tabId, change, tab) => {
  if (change.url) checkTab(tabId, change.url);
  else if (change.status === "loading" && tab.url) checkTab(tabId, tab.url);
});
api.tabs.onCreated.addListener((tab) => {
  if (tab.id !== undefined && (tab.pendingUrl || tab.url)) checkTab(tab.id, tab.pendingUrl || tab.url);
});

api.alarms.create("focusguard-sweep", { periodInMinutes: 0.5 });
api.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "focusguard-sweep") sweep();
});
api.runtime.onInstalled.addListener(() => sweep());
api.runtime.onStartup.addListener(() => sweep());
api.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg === "status") {
    loadPolicy(true).then((p) => sendResponse({ reachable: serviceReachable, active: !!p?.active, until: p?.until ?? null }));
    return true;
  }
  return false;
});
sweep();

// Exposed for the test suite (ignored by browsers).
if (typeof module !== "undefined") module.exports = { parseWatchPage, judgeVideo, youtubeVideoId, hostMatches, decide, _setPolicy: (p) => { policy = p; policyAt = Date.now(); } };
