"""Builds test vectors from the PC app's own code, so the phone is checked against the real thing."""
import json, random, sys
from datetime import datetime, timedelta
sys.path.insert(0, sys.argv[1])
from focusguard import schedule, link, config

rnd = random.Random(7)
def hm(): return f"{rnd.randrange(24):02d}:{rnd.choice([0, 0, 15, 30, 45, rnd.randrange(60)]):02d}"
cases = []
for i in range(3000):
    scheds = []
    for _ in range(rnd.randrange(0, 4)):
        start = hm(); end = start if rnd.random() < 0.05 else hm()
        scheds.append({"name": "s", "days": sorted(rnd.sample(range(7), rnd.randrange(0, 8))), "start": start, "end": end,
                       "enabled": rnd.random() > 0.1})
    if rnd.random() < 0.15 and scheds:  # back-to-back entries
        s = dict(scheds[0]); s["start"] = scheds[0]["end"]; s["end"] = hm(); scheds.append(s)
    now = datetime(2026, 11, 9) + timedelta(minutes=rnd.randrange(21 * 24 * 60), seconds=rnd.randrange(60))
    if scheds and rnd.random() < 0.3:  # exactly on a boundary
        h, m = map(int, rnd.choice([scheds[0]["start"], scheds[0]["end"]]).split(":"))
        now = now.replace(hour=h, minute=m, second=0)
    u, n = schedule.active_until(scheds, now), schedule.next_start(scheds, now)
    cases.append({"schedules": scheds, "now": now.isoformat(), "until": u.isoformat() if u else "", "next": n.isoformat() if n else ""})

code = link.new_code()
msgs = []
for big in (0, 0, 400, 5000):
    cfg = config.sanitize({"schedules": cases[5]["schedules"], "web": {"categories": ["social", "games"],
          "custom_blocked": [f"site{rnd.randrange(10**9)}.example.com" for _ in range(big)], "exceptions": ["old.reddit.com"]},
          "apps": {"categories": ["games"]}, "youtube": {"mode": "filter"}})
    cfg["session"] = {"until": 1800000000.5} if big else None
    state = link.build_state(cfg)
    msgs.append({"state": state, "pieces": link.seal(code, state)})
json.dump({"schedule": cases, "code": code, "code_formatted": link.format_code(code), "topic": link.topic(code), "messages": msgs},
          open(sys.argv[2], "w"))
print("pieces per message:", [len(m["pieces"]) for m in msgs], "longest piece:", max(len(p) for m in msgs for p in m["pieces"]))
