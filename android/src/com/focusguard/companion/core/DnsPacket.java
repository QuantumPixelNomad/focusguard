package com.focusguard.companion.core;

/**
 * Just enough IPv4 + UDP + DNS to answer or forward the DNS queries that reach the local VPN.
 * All methods are pure byte manipulation so they can be tested off the phone.
 */
public final class DnsPacket {
    public static final int TYPE_A = 1, TYPE_AAAA = 28;

    /** A parsed DNS-over-UDP query taken from an IPv4 packet. */
    public static final class Query {
        public byte[] srcAddr = new byte[4], dstAddr = new byte[4];
        public int srcPort, dstPort;
        public byte[] dns;       // the DNS message
        public String name;      // lower-case question name without the trailing dot
        public int qtype;
        public int questionEnd;  // offset in dns just after the first question
    }

    private DnsPacket() {}

    private static int u8(byte[] b, int i) {
        return b[i] & 0xff;
    }

    private static int u16(byte[] b, int i) {
        return (u8(b, i) << 8) | u8(b, i + 1);
    }

    private static void put16(byte[] b, int i, int v) {
        b[i] = (byte) (v >> 8);
        b[i + 1] = (byte) v;
    }

    /** Returns the query if the packet is an IPv4 UDP datagram to port 53 with one question, else null. */
    public static Query parse(byte[] pkt, int len) {
        if (len < 28 || (u8(pkt, 0) >> 4) != 4) return null;
        int ihl = (u8(pkt, 0) & 0x0f) * 4;
        if (ihl < 20 || len < ihl + 8 || u8(pkt, 9) != 17) return null;
        if ((u16(pkt, 6) & 0x3fff) != 0) return null; // fragmented
        int total = Math.min(u16(pkt, 2), len);
        Query q = new Query();
        System.arraycopy(pkt, 12, q.srcAddr, 0, 4);
        System.arraycopy(pkt, 16, q.dstAddr, 0, 4);
        q.srcPort = u16(pkt, ihl);
        q.dstPort = u16(pkt, ihl + 2);
        if (q.dstPort != 53) return null;
        int udpLen = u16(pkt, ihl + 4);
        int dnsLen = Math.min(udpLen, total - ihl) - 8;
        if (dnsLen < 12) return null;
        q.dns = new byte[dnsLen];
        System.arraycopy(pkt, ihl + 8, q.dns, 0, dnsLen);
        return parseQuestion(q) ? q : null;
    }

    private static boolean parseQuestion(Query q) {
        byte[] d = q.dns;
        if ((u8(d, 2) & 0x80) != 0) return false;   // a response, not a query
        if (u16(d, 4) < 1) return false;
        StringBuilder name = new StringBuilder();
        int i = 12;
        while (true) {
            if (i >= d.length) return false;
            int n = u8(d, i++);
            if (n == 0) break;
            if (n > 63 || i + n > d.length) return false; // compression is not valid in a question
            if (name.length() > 0) name.append('.');
            for (int k = 0; k < n; k++) {
                char c = (char) u8(d, i + k);
                name.append(c >= 'A' && c <= 'Z' ? (char) (c + 32) : c);
            }
            i += n;
        }
        if (i + 4 > d.length) return false;
        q.name = name.toString();
        q.qtype = u16(d, i);
        q.questionEnd = i + 4;
        return true;
    }

    /** A DNS answer that sends the name nowhere: 0.0.0.0 for A, :: for AAAA, empty otherwise. */
    public static byte[] blockedAnswer(Query q) {
        int rdlen = q.qtype == TYPE_A ? 4 : q.qtype == TYPE_AAAA ? 16 : 0;
        int answer = rdlen == 0 ? 0 : 12 + rdlen;
        byte[] out = new byte[q.questionEnd + answer];
        System.arraycopy(q.dns, 0, out, 0, q.questionEnd);
        out[2] = (byte) (0x80 | (q.dns[2] & 0x01)); // response, keep RD
        out[3] = (byte) 0x80;                         // RA, NOERROR
        put16(out, 4, 1);
        put16(out, 6, rdlen == 0 ? 0 : 1);
        put16(out, 8, 0);
        put16(out, 10, 0);
        if (rdlen != 0) {
            int i = q.questionEnd;
            put16(out, i, 0xc00c);          // pointer to the question name
            put16(out, i + 2, q.qtype);
            put16(out, i + 4, 1);           // class IN
            out[i + 9] = 60;                // TTL 60 s
            put16(out, i + 10, rdlen);      // address bytes stay zero
        }
        return out;
    }

    /** A SERVFAIL reply, used when no upstream server answers. */
    public static byte[] failAnswer(Query q) {
        byte[] out = new byte[q.questionEnd];
        System.arraycopy(q.dns, 0, out, 0, q.questionEnd);
        out[2] = (byte) (0x80 | (q.dns[2] & 0x01));
        out[3] = (byte) 0x82;
        put16(out, 4, 1);
        put16(out, 6, 0);
        put16(out, 8, 0);
        put16(out, 10, 0);
        return out;
    }

    /** Wraps a DNS reply in IPv4 + UDP headers addressed back to the sender of the query. */
    public static byte[] wrapReply(Query q, byte[] dns, int dnsLen) {
        int total = 28 + dnsLen;
        byte[] p = new byte[total];
        p[0] = 0x45;
        put16(p, 2, total);
        p[6] = 0x40;            // don't fragment
        p[8] = 64;              // TTL
        p[9] = 17;              // UDP
        System.arraycopy(q.dstAddr, 0, p, 12, 4);
        System.arraycopy(q.srcAddr, 0, p, 16, 4);
        int sum = 0;
        for (int i = 0; i < 20; i += 2) sum += u16(p, i);
        while ((sum >> 16) != 0) sum = (sum & 0xffff) + (sum >> 16);
        put16(p, 10, ~sum & 0xffff);
        put16(p, 20, q.dstPort);
        put16(p, 22, q.srcPort);
        put16(p, 24, 8 + dnsLen);
        // UDP checksum 0 = not used, which IPv4 allows
        System.arraycopy(dns, 0, p, 28, dnsLen);
        return p;
    }
}
