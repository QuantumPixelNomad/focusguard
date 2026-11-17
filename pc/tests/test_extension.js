// Run with: node tests/test_extension.js
"use strict";
const assert = require("node:assert");
const path = require("node:path");

// Minimal stand-ins for the browser APIs the background script touches at load time.
const noop = () => {};
const listener = { addListener: noop };
globalThis.chrome = {
  tabs: { onUpdated: listener, onCreated: listener, query: async () => [], get: async () => ({}), update: async () => {} },
  alarms: { create: noop, onAlarm: listener },
  runtime: { onInstalled: listener, onStartup: listener, onMessage: listener, getURL: (p) => "chrome-extension://x/" + p },
  storage: { local: { get: async () => ({}), set: noop } },
};
const pages = {};
globalThis.fetch = async (url) => {
  if (String(url).startsWith("http://127.0.0.1")) throw new Error("service not running in tests");
  const id = new URL(url).searchParams.get("v");
  return { ok: id in pages, text: async () => pages[id] };
};

const bg = require(path.join(__dirname, "..", "extension", "common", "background.js"));

const page = (category, title, extra = "") => `<html><head><title>${title} - YouTube</title>
<meta name="title" content="${title}"><meta name="keywords" content="k1, k2${extra}">
<meta itemprop="genre" content="${category.replace("&", "&amp;")}"></head><body><script>
var ytInitialPlayerResponse = {"microformat":{"playerMicroformatRenderer":{"ownerChannelName":"Some Channel",
"category":"${category.replace("&", "\\u0026")}"}}};</script></body></html>`;

// --- parsing ---
let info = bg.parseWatchPage(page("Science & Technology", "Intro to Neural Networks"));
assert.strictEqual(info.category, "Science & Technology");
assert.strictEqual(info.title, "Intro to Neural Networks");
assert.strictEqual(info.channel, "Some Channel");
assert.strictEqual(info.keywords, "k1, k2");
info = bg.parseWatchPage('<meta name="keywords" content="video, sharing"><script>var x = {"videoDetails":{"videoId":"a","title":"t","keywords":["linear algebra","3blue1brown"],"channelId":"c"}};</script>');
assert.match(info.keywords, /linear algebra/);
assert.match(info.keywords, /3blue1brown/);
info = bg.parseWatchPage('<meta itemprop="genre" content="Gaming"><title>x</title>');
assert.strictEqual(info.category, "Gaming");
assert.strictEqual(bg.parseWatchPage("<html>consent wall</html>").category, "");

// --- video ids ---
const id = (u) => bg.youtubeVideoId(new URL(u));
assert.strictEqual(id("https://www.youtube.com/watch?v=abc123XYZ_-&t=3"), "abc123XYZ_-");
assert.strictEqual(id("https://youtu.be/abc123XYZ_-?si=1"), "abc123XYZ_-");
assert.strictEqual(id("https://m.youtube.com/shorts/abc123XYZ_-"), "abc123XYZ_-");
assert.strictEqual(id("https://www.youtube.com/embed/abc123XYZ_-"), "abc123XYZ_-");
assert.strictEqual(id("https://www.youtube.com/results?search_query=x"), null);

// --- judging ---
const yt = { mode: "filter", allowed_categories: ["Education", "Science & Technology"],
  allow_keywords: ["pharmacology"], block_keywords: ["gameplay"], unknown: "block", block_shorts: true };
const v = (category, title) => ({ category, title, channel: "", keywords: "" });
assert.strictEqual(bg.judgeVideo(v("Education", "Calculus lecture 3"), yt), null);
assert.match(bg.judgeVideo(v("Gaming", "Elden Ring boss fight"), yt), /Gaming/);
assert.strictEqual(bg.judgeVideo(v("Entertainment", "Pharmacology made easy"), yt), null);
assert.match(bg.judgeVideo(v("Education", "Minecraft GAMEPLAY part 1"), yt), /gameplay/);
assert.match(bg.judgeVideo(v("Education", "pharmacology gameplay"), yt), /gameplay/);
assert.match(bg.judgeVideo(v("", ""), yt), /could not be determined/);
assert.strictEqual(bg.judgeVideo(v("", ""), { ...yt, unknown: "allow" }), null);

// --- host matching ---
assert.ok(bg.hostMatches("old.reddit.com", "reddit.com"));
assert.ok(bg.hostMatches("reddit.com", "reddit.com"));
assert.ok(!bg.hostMatches("notreddit.com", "reddit.com"));

// --- full decisions ---
(async () => {
  pages.study = page("Education", "Organic chemistry");
  pages.game = page("Gaming", "Speedrun highlights");
  const policy = { active: true, until: Date.now() / 1000 + 3600, blocked_domains: ["reddit.com", "twitch.tv"],
    exceptions: ["study.reddit.com"], youtube: yt };
  const run = async (url, p = policy) => { bg._setPolicy(p); return bg.decide(url); };

  assert.strictEqual(await run("https://www.youtube.com/watch?v=study"), null);
  assert.match((await run("https://www.youtube.com/watch?v=game")).reason, /Gaming/);
  assert.match((await run("https://www.youtube.com/watch?v=missing")).reason, /could not be determined/);
  assert.match((await run("https://www.youtube.com/shorts/study")).reason, /Shorts/);
  assert.strictEqual(await run("https://www.youtube.com/"), null);
  assert.strictEqual(await run("https://www.youtube.com/results?search_query=chemistry"), null);
  assert.match((await run("https://old.reddit.com/r/all")).reason, /reddit\.com/);
  assert.strictEqual(await run("https://study.reddit.com/"), null);
  assert.strictEqual(await run("https://en.wikipedia.org/wiki/Chemistry"), null);
  assert.strictEqual(await run("about:blank"), null);
  assert.match((await run("https://youtu.be/study", { ...policy, youtube: { ...yt, mode: "block" } })).reason, /YouTube is blocked/);
  assert.strictEqual(await run("https://www.youtube.com/watch?v=game", { ...policy, youtube: { ...yt, mode: "allow" } }), null);
  assert.strictEqual(await run("https://www.youtube.com/watch?v=game", { ...policy, active: false }), null);
  assert.strictEqual(await run("https://reddit.com/", { ...policy, active: false }), null);
  console.log("extension tests passed");
})().catch((err) => { console.error(err); process.exit(1); });
