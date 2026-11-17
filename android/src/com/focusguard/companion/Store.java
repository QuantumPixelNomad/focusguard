package com.focusguard.companion;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONException;
import org.json.JSONObject;

import java.util.HashMap;
import java.util.Iterator;
import java.util.Map;

/** Everything the app remembers between starts. */
final class Store {
    static final String BLOCK = "block", ALLOW = "allow";
    private final SharedPreferences prefs;

    Store(Context ctx) {
        prefs = ctx.getSharedPreferences("focusguard", Context.MODE_PRIVATE);
    }

    String code() {
        return prefs.getString("code", null);
    }

    String server() {
        return prefs.getString("server", null);
    }

    void setLink(String code, String server) {
        prefs.edit().putString("code", code).putString("server", server).apply();
    }

    void clearLink() {
        prefs.edit().remove("code").remove("server").remove("policy").remove("policy_at").apply();
    }

    String policyJson() {
        return prefs.getString("policy", null);
    }

    long policyAt() {
        return prefs.getLong("policy_at", 0);
    }

    void setPolicy(String json, long at) {
        prefs.edit().putString("policy", json).putLong("policy_at", at).apply();
    }

    /** What to do with the YouTube apps when the PC is set to filter videos: block or allow. */
    String youtubeOnPhone() {
        return prefs.getString("yt_phone", BLOCK);
    }

    void setYoutubeOnPhone(String v) {
        prefs.edit().putString("yt_phone", v).apply();
    }

    /** package name -> BLOCK or ALLOW, the choices made on this phone. */
    Map<String, String> overrides() {
        Map<String, String> out = new HashMap<>();
        try {
            JSONObject o = new JSONObject(prefs.getString("overrides", "{}"));
            for (Iterator<String> it = o.keys(); it.hasNext(); ) {
                String k = it.next();
                out.put(k, o.getString(k));
            }
        } catch (JSONException ignored) {
        }
        return out;
    }

    void setOverride(String pkg, String value) {
        Map<String, String> all = overrides();
        if (value == null) all.remove(pkg);
        else all.put(pkg, value);
        prefs.edit().putString("overrides", new JSONObject(all).toString()).apply();
    }
}
