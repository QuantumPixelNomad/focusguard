package com.focusguard.companion.core;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import java.util.zip.DataFormatException;
import java.util.zip.Inflater;

import javax.crypto.Cipher;
import javax.crypto.Mac;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;

/**
 * Link protocol v1. The PC publishes its state to a topic on an ntfy server; the phone reads it.
 *
 *   link code  16 characters shown by the PC app
 *   master     HMAC-SHA256(key="focusguard-link-v1", code)
 *   topic      "fg" + first 40 hex characters of HMAC-SHA256(master, "topic")
 *   key        HMAC-SHA256(master, "enc")           (AES-256-GCM)
 *   blob       12-byte nonce + AES-GCM(key, nonce, zlib(state JSON), aad="FG1")
 *   message    "FG1.<id>.<index>.<count>.<base64url piece of blob>"   (pieces keep each message small)
 *
 * The relay only ever sees the topic name and encrypted bytes.
 */
public final class Relay {
    public static final String DEFAULT_SERVER = "https://ntfy.sh";
    public static final int CODE_LENGTH = 16;
    private static final String ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789";

    public interface Listener {
        /** A complete, authentic state arrived. */
        void onState(String json);

        /** The connection is open and the backlog has been requested. */
        void onConnected();
    }

    private Relay() {}

    /** Upper-cases and strips separators. Returns null if it is not a complete link code. */
    public static String normalizeCode(String text) {
        if (text == null) return null;
        StringBuilder sb = new StringBuilder();
        for (char c : text.toUpperCase(Locale.ROOT).toCharArray()) {
            if (ALPHABET.indexOf(c) >= 0) sb.append(c);
            else if (c != '-' && c != ' ') return null;
        }
        return sb.length() == CODE_LENGTH ? sb.toString() : null;
    }

    public static byte[] hmac(byte[] key, byte[] msg) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(key, "HmacSHA256"));
            return mac.doFinal(msg);
        } catch (java.security.GeneralSecurityException e) {
            throw new IllegalStateException(e);
        }
    }

    private static byte[] ascii(String s) {
        return s.getBytes(StandardCharsets.US_ASCII);
    }

    public static byte[] master(String code) {
        return hmac(ascii("focusguard-link-v1"), ascii(code));
    }

    public static String topic(String code) {
        byte[] t = hmac(master(code), ascii("topic"));
        StringBuilder sb = new StringBuilder("fg");
        for (int i = 0; i < 20; i++) sb.append(String.format(Locale.ROOT, "%02x", t[i] & 0xff));
        return sb.toString();
    }

    public static byte[] key(String code) {
        return hmac(master(code), ascii("enc"));
    }

    /** Decrypts and unpacks a blob. Throws if it was not made with this key. */
    public static String open(byte[] key, byte[] blob) throws IOException {
        if (blob.length < 12 + 16) throw new IOException("Message too short.");
        byte[] packed;
        try {
            Cipher c = Cipher.getInstance("AES/GCM/NoPadding");
            c.init(Cipher.DECRYPT_MODE, new SecretKeySpec(key, "AES"), new GCMParameterSpec(128, blob, 0, 12));
            c.updateAAD(ascii("FG1"));
            packed = c.doFinal(blob, 12, blob.length - 12);
        } catch (java.security.GeneralSecurityException e) {
            throw new IOException("Message was not made with this link code.");
        }
        Inflater inf = new Inflater();
        inf.setInput(packed);
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        try {
            while (!inf.finished()) {
                int n = inf.inflate(buf);
                if (n == 0 && (inf.needsInput() || inf.needsDictionary())) throw new IOException("Damaged message.");
                out.write(buf, 0, n);
                if (out.size() > 8 * 1024 * 1024) throw new IOException("Message too large.");
            }
        } catch (DataFormatException e) {
            throw new IOException("Damaged message.");
        } finally {
            inf.end();
        }
        return new String(out.toByteArray(), StandardCharsets.UTF_8);
    }

    /** Puts multi-piece messages back together. Feed it every message body; it returns a state when one completes. */
    public static final class Assembler {
        private final byte[] key;
        private final Map<String, String[]> partial = new HashMap<>();

        public Assembler(byte[] key) {
            this.key = key;
        }

        public String offer(String body) {
            if (body == null) return null;
            String[] f = body.trim().split("\\.");
            if (f.length != 5 || !f[0].equals("FG1")) return null;
            int index, count;
            try {
                index = Integer.parseInt(f[2]);
                count = Integer.parseInt(f[3]);
            } catch (NumberFormatException e) {
                return null;
            }
            if (count < 1 || count > 200 || index < 0 || index >= count) return null;
            String[] pieces = partial.get(f[1]);
            if (pieces == null || pieces.length != count) {
                if (partial.size() > 50) partial.clear();
                pieces = new String[count];
                partial.put(f[1], pieces);
            }
            pieces[index] = f[4];
            StringBuilder all = new StringBuilder();
            for (String p : pieces) {
                if (p == null) return null;
                all.append(p);
            }
            partial.remove(f[1]);
            try {
                return open(key, Base64.getUrlDecoder().decode(all.toString()));
            } catch (IOException | IllegalArgumentException e) {
                return null;
            }
        }
    }

    /** One subscription to the topic. run() blocks, delivering states, until close() or a network error. */
    public static final class Stream {
        private final String server, topic;
        private final Assembler assembler;
        private volatile HttpURLConnection conn;
        private volatile boolean closed;

        public Stream(String server, String code) {
            String s = server == null || server.trim().isEmpty() ? DEFAULT_SERVER : server.trim();
            while (s.endsWith("/")) s = s.substring(0, s.length() - 1);
            this.server = s;
            this.topic = topic(code);
            this.assembler = new Assembler(key(code));
        }

        /**
         * @param keepOpen false reads what the relay has stored and returns; true keeps listening.
         */
        public void run(boolean keepOpen, Listener listener) throws IOException {
            URL url = new URL(server + "/" + topic + "/json?since=all" + (keepOpen ? "" : "&poll=1"));
            HttpURLConnection c = (HttpURLConnection) url.openConnection();
            conn = c;
            try {
                c.setConnectTimeout(15000);
                c.setReadTimeout(120000); // the relay sends a keep-alive line well within this
                c.setUseCaches(false);
                c.setRequestProperty("User-Agent", "FocusGuard-Android");
                c.setRequestProperty("Accept-Encoding", "identity"); // a compressed stream would be buffered
                int status = c.getResponseCode();
                if (status != 200) throw new IOException("The relay answered " + status + ".");
                listener.onConnected();
                BufferedReader r = new BufferedReader(new InputStreamReader(c.getInputStream(), StandardCharsets.UTF_8));
                String line;
                while (!closed && (line = r.readLine()) != null) {
                    if (line.isEmpty()) continue;
                    try {
                        JSONObject o = new JSONObject(line);
                        if (!"message".equals(o.optString("event"))) continue;
                        String state = assembler.offer(o.optString("message", null));
                        if (state != null) listener.onState(state);
                    } catch (org.json.JSONException ignored) {
                    }
                }
            } finally {
                c.disconnect();
            }
        }

        public void close() {
            closed = true;
            final HttpURLConnection c = conn;
            if (c != null) new Thread(new Runnable() { @Override public void run() { c.disconnect(); } }).start();
        }
    }
}
