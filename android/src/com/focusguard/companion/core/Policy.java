package com.focusguard.companion.core;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/** The PC's rules as last received, plus the maths to decide whether a block is running now. */
public final class Policy {
    public static final class State {
        public boolean active;
        public long untilMs;      // 0 when idle
        public String reason;     // "schedule", "session", "schedule and session"
        public long nextStartMs;  // 0 when nothing is scheduled
    }

    public String pcName = "";
    public double pcNow;           // PC clock (epoch seconds) when the state was produced
    public long receivedAtMs;      // phone clock when it arrived
    public double sessionUntil;    // epoch seconds, 0 if none
    public final List<Schedule.Entry> schedules = new ArrayList<>();
    public final List<String> customBlocked = new ArrayList<>();
    public final List<String> exceptions = new ArrayList<>();
    public String youtubeMode = "allow";
    public final Set<String> appCategories = new HashSet<>();
    public final Set<String> webCategories = new HashSet<>();
    public boolean strict;
    public String raw = "";

    public static Policy parse(String json, long receivedAtMs) throws JSONException {
        JSONObject o = new JSONObject(json);
        if (o.optInt("v", 0) != 1) throw new JSONException("Unsupported link version");
        Policy p = new Policy();
        p.raw = json;
        p.receivedAtMs = receivedAtMs;
        p.pcName = o.optString("name", "");
        p.pcNow = o.optDouble("now", 0);
        p.sessionUntil = o.isNull("session_until") ? 0 : o.optDouble("session_until", 0);
        JSONArray arr = o.optJSONArray("schedules");
        for (int i = 0; arr != null && i < arr.length(); i++) {
            JSONObject s = arr.getJSONObject(i);
            Schedule.Entry e = new Schedule.Entry();
            e.name = s.optString("name", "");
            e.start = Schedule.minutes(s.getString("start"));
            e.end = Schedule.minutes(s.getString("end"));
            e.enabled = s.optBoolean("enabled", true);
            JSONArray days = s.optJSONArray("days");
            for (int d = 0; days != null && d < days.length(); d++) {
                int day = days.getInt(d);
                if (day >= 0 && day <= 6) e.days[day] = true;
            }
            p.schedules.add(e);
        }
        strings(o.optJSONArray("custom_blocked"), p.customBlocked);
        strings(o.optJSONArray("exceptions"), p.exceptions);
        p.youtubeMode = o.optString("youtube_mode", "allow");
        List<String> tmp = new ArrayList<>();
        strings(o.optJSONArray("app_categories"), tmp);
        p.appCategories.addAll(tmp);
        tmp.clear();
        strings(o.optJSONArray("web_categories"), tmp);
        p.webCategories.addAll(tmp);
        p.strict = o.optBoolean("strict", false);
        return p;
    }

    private static void strings(JSONArray arr, List<String> out) {
        for (int i = 0; arr != null && i < arr.length(); i++) {
            String s = arr.optString(i, "");
            if (!s.isEmpty()) out.add(s);
        }
    }

    /** The session end in ms, 0 if no session. Both clocks are assumed to be set from the network. */
    public long sessionUntilPhoneMs() {
        return sessionUntil <= 0 ? 0 : (long) (sessionUntil * 1000.0);
    }

    public State state(long nowMs, ZoneId zone) {
        State st = new State();
        LocalDateTime now = LocalDateTime.ofInstant(Instant.ofEpochMilli(nowMs), zone);
        LocalDateTime sched = Schedule.activeUntil(schedules, now);
        if (sched != null) {
            st.untilMs = sched.atZone(zone).toInstant().toEpochMilli();
            st.reason = "schedule";
        }
        long sess = sessionUntilPhoneMs();
        if (sess > nowMs) {
            if (sess > st.untilMs) st.untilMs = sess;
            st.reason = st.reason != null ? "schedule and session" : "session";
        }
        st.active = st.untilMs > 0;
        LocalDateTime next = Schedule.nextStart(schedules, now);
        st.nextStartMs = next == null ? 0 : next.atZone(zone).toInstant().toEpochMilli();
        return st;
    }
}
