package com.focusguard.companion.core;

import java.util.Collection;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;

/** Blocked domains with exceptions. A domain covers itself and every subdomain. */
public final class DomainSet {
    private final Set<String> blocked = new HashSet<>();
    private final Set<String> exceptions = new HashSet<>();

    public DomainSet(Collection<String> blocked, Collection<String> exceptions) {
        for (String d : blocked) this.blocked.add(d.toLowerCase(Locale.ROOT));
        for (String d : exceptions) this.exceptions.add(d.toLowerCase(Locale.ROOT));
    }

    public boolean isEmpty() {
        return blocked.isEmpty();
    }

    public int size() {
        return blocked.size();
    }

    private static boolean covered(Set<String> set, String host) {
        String h = host;
        while (true) {
            if (set.contains(h)) return true;
            int dot = h.indexOf('.');
            if (dot < 0) return false;
            h = h.substring(dot + 1);
        }
    }

    public boolean isBlocked(String host) {
        if (host == null || host.isEmpty()) return false;
        String h = host.toLowerCase(Locale.ROOT);
        if (h.endsWith(".")) h = h.substring(0, h.length() - 1);
        return covered(blocked, h) && !covered(exceptions, h);
    }
}
