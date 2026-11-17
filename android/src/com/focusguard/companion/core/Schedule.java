package com.focusguard.companion.core;

import java.time.LocalDateTime;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.List;

/**
 * Weekly schedule maths, a line-for-line port of focusguard/schedule.py on the PC.
 * Days are 0=Monday .. 6=Sunday; times are local "HH:MM".
 * An entry whose end is not after its start runs past midnight into the next day.
 */
public final class Schedule {
    public static final class Entry {
        public String name = "";
        public boolean[] days = new boolean[7];
        public int start, end; // minutes after midnight
        public boolean enabled = true;

        boolean anyDay() {
            for (boolean d : days) if (d) return true;
            return false;
        }
    }

    private Schedule() {}

    public static int minutes(String hm) {
        String[] p = hm.split(":");
        return Integer.parseInt(p[0]) * 60 + Integer.parseInt(p[1]);
    }

    private static LocalDateTime at(LocalDateTime day, int minutes) {
        return day.truncatedTo(ChronoUnit.DAYS).plusMinutes(minutes);
    }

    /** When the entry's current window ends, or null if it is not running at now. */
    public static LocalDateTime entryEnd(Entry e, LocalDateTime now) {
        if (!e.enabled || !e.anyDay()) return null;
        int t = now.getHour() * 60 + now.getMinute();
        int today = now.getDayOfWeek().getValue() - 1;
        int yesterday = (today + 6) % 7;
        if (e.start < e.end) {
            return (e.days[today] && e.start <= t && t < e.end) ? at(now, e.end) : null;
        }
        if (e.days[today] && t >= e.start) return at(now.plusDays(1), e.end);
        if (e.days[yesterday] && t < e.end) return at(now, e.end);
        return null;
    }

    /** End of the block running at now, following back-to-back entries. Null if idle. */
    public static LocalDateTime activeUntil(List<Entry> entries, LocalDateTime now) {
        LocalDateTime until = null, probe = now;
        for (int i = 0; i < 16; i++) {
            LocalDateTime latest = null;
            for (Entry e : entries) {
                LocalDateTime end = entryEnd(e, probe);
                if (end != null && (latest == null || end.isAfter(latest))) latest = end;
            }
            if (latest == null) break;
            if (until != null && !latest.isAfter(until)) break;
            until = latest;
            probe = latest;
        }
        return until;
    }

    public static LocalDateTime nextStart(List<Entry> entries, LocalDateTime now) {
        LocalDateTime best = null;
        for (Entry e : entries) {
            if (!e.enabled || !e.anyDay()) continue;
            for (int offset = 0; offset < 8; offset++) {
                LocalDateTime day = now.plusDays(offset);
                if (!e.days[day.getDayOfWeek().getValue() - 1]) continue;
                LocalDateTime c = at(day, e.start);
                if (c.isAfter(now) && (best == null || c.isBefore(best))) best = c;
            }
        }
        return best;
    }

    public static List<Entry> copy(List<Entry> in) {
        return new ArrayList<>(in);
    }
}
