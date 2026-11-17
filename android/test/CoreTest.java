import com.focusguard.companion.core.*;
import org.json.*;
import java.nio.file.*;
import java.time.*;
import java.util.*;

public class CoreTest {
    static int checks = 0, failed = 0;
    static void check(boolean ok, String what) { checks++; if (!ok) { failed++; System.out.println("FAIL: " + what); } }

    public static void main(String[] a) throws Exception {
        JSONObject v = new JSONObject(new String(Files.readAllBytes(Paths.get(a[0])), "UTF-8"));
        // schedule parity with the PC's schedule.py
        JSONArray cases = v.getJSONArray("schedule");
        for (int i = 0; i < cases.length(); i++) {
            JSONObject c = cases.getJSONObject(i);
            JSONObject st = new JSONObject().put("v", 1).put("schedules", c.getJSONArray("schedules"));
            Policy p = Policy.parse(st.toString(), 0);
            LocalDateTime now = LocalDateTime.parse(c.getString("now"));
            LocalDateTime u = Schedule.activeUntil(p.schedules, now), n = Schedule.nextStart(p.schedules, now);
            String us = u == null ? "" : u.toString(), ns = n == null ? "" : n.toString();
            check(us.equals(norm(c.optString("until", ""))), "until case " + i + " java=" + us + " py=" + c.optString("until"));
            check(ns.equals(norm(c.optString("next", ""))), "next case " + i + " java=" + ns + " py=" + c.optString("next"));
        }
        // relay messages made by the PC's link.py
        String code = v.getString("code");
        check(Relay.topic(code).equals(v.getString("topic")), "topic");
        check(code.equals(Relay.normalizeCode(v.getString("code_formatted").toLowerCase())), "normalize");
        check(Relay.normalizeCode("ABCD") == null && Relay.normalizeCode("OOOO-OOOO-OOOO-OOOO") == null, "bad codes");
        JSONArray msgs = v.getJSONArray("messages");
        for (int i = 0; i < msgs.length(); i++) {
            JSONObject m = msgs.getJSONObject(i);
            JSONArray pieces = m.getJSONArray("pieces");
            Relay.Assembler as = new Relay.Assembler(Relay.key(code));
            String got = null;
            List<Integer> order = new ArrayList<>();
            for (int k = 0; k < pieces.length(); k++) order.add(k);
            Collections.shuffle(order, new Random(i));
            for (int k : order) { String r = as.offer(pieces.getString(k)); if (r != null) got = r; }
            check(got != null && same(new JSONObject(got), m.getJSONObject("state")), "message " + i + " (" + pieces.length() + " pieces)");
            Relay.Assembler wrong = new Relay.Assembler(Relay.key("ABCDEFGHJKMNPQRS"));
            String bad = null;
            for (int k = 0; k < pieces.length(); k++) { String r = wrong.offer(pieces.getString(k)); if (r != null) bad = r; }
            check(bad == null, "wrong key rejected " + i);
            String p0 = pieces.getString(0);
            String tampered = p0.substring(0, p0.length() - 3) + (p0.endsWith("AAA") ? "BBB" : "AAA");
            Relay.Assembler t = new Relay.Assembler(Relay.key(code));
            String tr = null;
            for (int k = 0; k < pieces.length(); k++) { String r = t.offer(k == 0 ? tampered : pieces.getString(k)); if (r != null) tr = r; }
            check(tr == null, "tampered rejected " + i);
        }
        Relay.Assembler junk = new Relay.Assembler(Relay.key(code));
        for (String s : new String[]{null, "", "hello", "FG1.x.0.1.", "FG1.x.5.2.abc", "FG1.x.0.0.abc", "FG1.x.a.b.c", "FG1.x.0.1.!!!!"}) check(junk.offer(s) == null, "junk " + s);

        // policy state: session and schedule together
        ZoneId z = ZoneId.of("Asia/Riyadh");
        long t0 = LocalDateTime.parse("2026-11-16T10:00:00").atZone(z).toInstant().toEpochMilli(); // a Monday
        String sched = "[{\"name\":\"Study\",\"days\":[0,1,2,3,4],\"start\":\"09:00\",\"end\":\"12:00\",\"enabled\":true}]";
        Policy p = Policy.parse("{\"v\":1,\"now\":1,\"session_until\":null,\"schedules\":" + sched + "}", t0);
        Policy.State s = p.state(t0, z);
        check(s.active && "schedule".equals(s.reason) && s.untilMs == t0 + 2 * 3600_000L, "schedule active");
        s = p.state(t0 + 3 * 3600_000L, z);
        check(!s.active && s.nextStartMs == t0 + 23 * 3600_000L, "idle, next tomorrow 09:00");
        p = Policy.parse("{\"v\":1,\"now\":1,\"session_until\":" + ((t0 / 1000) + 4 * 3600) + ",\"schedules\":" + sched + "}", t0);
        s = p.state(t0, z);
        check(s.active && "schedule and session".equals(s.reason) && s.untilMs == t0 + 4 * 3600_000L, "session outlasts schedule");
        s = p.state(t0 + 5 * 3600_000L, z);
        check(!s.active, "session over");
        p = Policy.parse("{\"v\":1,\"now\":1,\"session_until\":" + ((t0 / 1000) + 600) + ",\"schedules\":[]}", t0);
        s = p.state(t0, z);
        check(s.active && "session".equals(s.reason) && s.nextStartMs == 0, "session only");
        try { Policy.parse("{\"v\":2}", 0); check(false, "v2 refused"); } catch (JSONException e) { check(true, ""); }

        // domains
        DomainSet d = new DomainSet(Arrays.asList("reddit.com", "Twitch.tv", "news.google.com"), Arrays.asList("old.reddit.com"));
        check(d.isBlocked("reddit.com") && d.isBlocked("www.reddit.com") && d.isBlocked("WWW.Reddit.com."), "blocked + subdomain");
        check(!d.isBlocked("old.reddit.com") && !d.isBlocked("x.old.reddit.com"), "exception wins");
        check(!d.isBlocked("notreddit.com") && !d.isBlocked("google.com") && d.isBlocked("news.google.com") && !d.isBlocked("com") && !d.isBlocked(""), "non-matches");

        // DNS packets
        byte[] q = query("www.Reddit.com", 1, 0x1234);
        DnsPacket.Query pq = DnsPacket.parse(q, q.length);
        check(pq != null && pq.name.equals("www.reddit.com") && pq.qtype == 1 && pq.srcPort == 40000, "parse query");
        byte[] ans = DnsPacket.blockedAnswer(pq);
        byte[] ip = DnsPacket.wrapReply(pq, ans, ans.length);
        check(ip.length == 28 + ans.length && ip[12] == 10 && ip[15] == 2 && ip[16] == 10 && ip[19] == 1, "reply addressed back");
        check(((ip[20] & 255) << 8 | (ip[21] & 255)) == 53 && ((ip[22] & 255) << 8 | (ip[23] & 255)) == 40000, "reply ports");
        int sum = 0; for (int i = 0; i < 20; i += 2) sum += ((ip[i] & 255) << 8) | (ip[i + 1] & 255);
        while ((sum >> 16) != 0) sum = (sum & 0xffff) + (sum >> 16);
        check(sum == 0xffff, "IP checksum");
        check(ans[0] == 0x12 && ans[1] == 0x34 && (ans[2] & 0x80) != 0 && (ans[3] & 15) == 0 && ans[7] == 1 && ans.length == pq.questionEnd + 16, "A answer 0.0.0.0");
        // the answer must be readable by a real DNS parser: decode with a tiny one
        check(ans[pq.questionEnd] == (byte) 0xc0 && ans[pq.questionEnd + 1] == 12 && ans[pq.questionEnd + 11] == 4, "A rdata length");
        byte[] q6 = query("a.b", 28, 7);
        DnsPacket.Query p6 = DnsPacket.parse(q6, q6.length);
        check(DnsPacket.blockedAnswer(p6).length == p6.questionEnd + 28, "AAAA answer");
        byte[] q65 = query("a.b", 65, 7);
        DnsPacket.Query p65 = DnsPacket.parse(q65, q65.length);
        byte[] a65 = DnsPacket.blockedAnswer(p65);
        check(a65.length == p65.questionEnd && a65[7] == 0, "HTTPS record gets empty answer");
        check((DnsPacket.failAnswer(pq)[3] & 15) == 2, "servfail");
        byte[] tcp = q.clone(); tcp[9] = 6; check(DnsPacket.parse(tcp, tcp.length) == null, "tcp ignored");
        byte[] other = q.clone(); other[23] = 54; check(DnsPacket.parse(other, other.length) == null, "port 54 ignored");
        byte[] v6 = q.clone(); v6[0] = 0x60; check(DnsPacket.parse(v6, v6.length) == null, "ipv6 ignored");
        Random rnd = new Random(1);
        for (int i = 0; i < 20000; i++) { // garbage must never throw
            byte[] g = q.clone();
            for (int k = 0; k < 4; k++) g[rnd.nextInt(g.length)] = (byte) rnd.nextInt(256);
            int len = rnd.nextInt(g.length + 1);
            try { DnsPacket.Query r = DnsPacket.parse(g, len); if (r != null) { DnsPacket.wrapReply(r, DnsPacket.blockedAnswer(r), DnsPacket.blockedAnswer(r).length); } }
            catch (RuntimeException e) { check(false, "garbage threw " + e); break; }
        }
        System.out.println(checks + " checks, " + failed + " failed");
        System.exit(failed == 0 ? 0 : 1);
    }

    static boolean same(Object a, Object b) throws JSONException {
        if (a instanceof JSONObject && b instanceof JSONObject) {
            JSONObject x = (JSONObject) a, y = (JSONObject) b;
            if (x.length() != y.length()) return false;
            for (Iterator<String> it = x.keys(); it.hasNext(); ) { String k = it.next(); if (!y.has(k) || !same(x.get(k), y.get(k))) return false; }
            return true;
        }
        if (a instanceof JSONArray && b instanceof JSONArray) {
            JSONArray x = (JSONArray) a, y = (JSONArray) b;
            if (x.length() != y.length()) return false;
            for (int i = 0; i < x.length(); i++) if (!same(x.get(i), y.get(i))) return false;
            return true;
        }
        if (a instanceof Number && b instanceof Number) return ((Number) a).doubleValue() == ((Number) b).doubleValue();
        return a.equals(b);
    }

    static String norm(String iso) { // python prints 2026-11-16T09:00:00, java drops :00 seconds
        return iso.isEmpty() ? "" : LocalDateTime.parse(iso).toString();
    }

    static byte[] query(String name, int type, int id) {
        java.io.ByteArrayOutputStream dns = new java.io.ByteArrayOutputStream();
        dns.write(id >> 8); dns.write(id); dns.write(1); dns.write(0);
        dns.write(0); dns.write(1); for (int i = 0; i < 6; i++) dns.write(0);
        for (String l : name.split("\\.")) { dns.write(l.length()); for (char c : l.toCharArray()) dns.write(c); }
        dns.write(0); dns.write(0); dns.write(type); dns.write(0); dns.write(1);
        byte[] d = dns.toByteArray();
        byte[] p = new byte[28 + d.length];
        p[0] = 0x45; p[2] = (byte) (p.length >> 8); p[3] = (byte) p.length; p[8] = 64; p[9] = 17;
        p[12] = 10; p[13] = 111; p[14] = (byte) 222; p[15] = 1; p[16] = 10; p[17] = 111; p[18] = (byte) 222; p[19] = 2;
        p[20] = (byte) (40000 >> 8); p[21] = (byte) 40000; p[22] = 0; p[23] = 53;
        p[24] = (byte) ((8 + d.length) >> 8); p[25] = (byte) (8 + d.length);
        System.arraycopy(d, 0, p, 28, d.length);
        return p;
    }
}
