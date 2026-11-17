package com.focusguard.companion;

import android.content.Context;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.telecom.TelecomManager;

import com.focusguard.companion.core.Policy;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/** Turns the PC's categories plus this phone's own choices into the set of Android apps to block. */
final class AppRules {
    static final class AppRow {
        String pkg, label;
        String byPc;      // why the PC's rules block it, or null
        String override;  // Store.BLOCK, Store.ALLOW or null
        boolean essential;

        boolean blocked() {
            if (essential) return false;
            if (override != null) return Store.BLOCK.equals(override);
            return byPc != null;
        }
    }

    private final Context ctx;
    private final Map<String, Set<String>> known = new HashMap<>();
    final Map<String, List<String>> webDomains = new HashMap<>();
    final Map<String, String> webLabels = new HashMap<>();

    AppRules(Context ctx) {
        this.ctx = ctx.getApplicationContext();
        try {
            JSONObject o = new JSONObject(asset("app_packages.json"));
            for (java.util.Iterator<String> it = o.keys(); it.hasNext(); ) {
                String k = it.next();
                Set<String> set = new HashSet<>();
                JSONArray a = o.getJSONArray(k);
                for (int i = 0; i < a.length(); i++) set.add(a.getString(i));
                known.put(k, set);
            }
            JSONObject w = new JSONObject(asset("web_categories.json"));
            for (java.util.Iterator<String> it = w.keys(); it.hasNext(); ) {
                String k = it.next();
                JSONObject cat = w.getJSONObject(k);
                List<String> list = new ArrayList<>();
                JSONArray a = cat.getJSONArray("domains");
                for (int i = 0; i < a.length(); i++) list.add(a.getString(i));
                webDomains.put(k, list);
                webLabels.put(k, cat.optString("label", k));
            }
        } catch (Exception e) {
            throw new IllegalStateException("Bundled lists are unreadable", e);
        }
    }

    private String asset(String name) throws java.io.IOException {
        try (InputStream in = ctx.getAssets().open(name)) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            return new String(out.toByteArray(), StandardCharsets.UTF_8);
        }
    }

    private boolean in(String list, String pkg) {
        Set<String> s = known.get(list);
        return s != null && s.contains(pkg);
    }

    /** True when the YouTube apps and site are blocked on this phone under the given rules. */
    static boolean youtubeBlocked(Policy p, String youtubeOnPhone) {
        if ("block".equals(p.youtubeMode)) return true;
        return "filter".equals(p.youtubeMode) && Store.BLOCK.equals(youtubeOnPhone);
    }

    /** Why the PC's rules block this app, or null if they do not. */
    String reason(Policy p, String youtubeOnPhone, String pkg, ApplicationInfo info) {
        if (p == null) return null;
        int cat = info == null ? ApplicationInfo.CATEGORY_UNDEFINED : info.category;
        boolean game = cat == ApplicationInfo.CATEGORY_GAME
                || (info != null && (info.flags & ApplicationInfo.FLAG_IS_GAME) != 0);
        if (in("youtube", pkg)) return youtubeBlocked(p, youtubeOnPhone) ? "YouTube" : null;
        if (p.appCategories.contains("games") && (game || in("games", pkg))) return "Games";
        if (p.appCategories.contains("media") && (cat == ApplicationInfo.CATEGORY_VIDEO
                || cat == ApplicationInfo.CATEGORY_AUDIO || in("video", pkg) || in("media_players", pkg))) {
            return "Entertainment and media players";
        }
        if (p.appCategories.contains("chat") && (cat == ApplicationInfo.CATEGORY_SOCIAL || in("social", pkg))) {
            return "Social and chat apps";
        }
        if (p.webCategories.contains("social") && (cat == ApplicationInfo.CATEGORY_SOCIAL || in("social", pkg))) {
            return "Social media";
        }
        if (p.webCategories.contains("games") && (game || in("games", pkg))) return "Games";
        if (p.webCategories.contains("video") && in("video", pkg)) return "Video and streaming";
        if (p.webCategories.contains("news") && (cat == ApplicationInfo.CATEGORY_NEWS || in("news", pkg))) return "News";
        if (p.webCategories.contains("shopping") && in("shopping", pkg)) return "Shopping";
        if (p.webCategories.contains("gambling") && in("gambling", pkg)) return "Gambling and betting";
        return null;
    }

    /** Apps that are never blocked: this app, the home screen, the phone app and Settings. */
    Set<String> essentials() {
        Set<String> out = new HashSet<>();
        out.add(ctx.getPackageName());
        out.add("com.android.settings");
        out.add("com.android.systemui");
        PackageManager pm = ctx.getPackageManager();
        Intent home = new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME);
        for (ResolveInfo r : pm.queryIntentActivities(home, 0)) out.add(r.activityInfo.packageName);
        try {
            TelecomManager tm = (TelecomManager) ctx.getSystemService(Context.TELECOM_SERVICE);
            if (tm != null && tm.getDefaultDialerPackage() != null) out.add(tm.getDefaultDialerPackage());
        } catch (RuntimeException ignored) {
        }
        return out;
    }

    /** Every app that has a launcher icon, with what happens to it during a block. */
    List<AppRow> rows(Policy p, Store store) {
        PackageManager pm = ctx.getPackageManager();
        Map<String, String> overrides = store.overrides();
        Set<String> essential = essentials();
        String yt = store.youtubeOnPhone();
        Intent launcher = new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER);
        Map<String, AppRow> rows = new HashMap<>();
        for (ResolveInfo r : pm.queryIntentActivities(launcher, 0)) {
            String pkg = r.activityInfo.packageName;
            if (rows.containsKey(pkg)) continue;
            AppRow row = new AppRow();
            row.pkg = pkg;
            ApplicationInfo info = r.activityInfo.applicationInfo;
            CharSequence label = info == null ? null : pm.getApplicationLabel(info);
            row.label = label == null ? pkg : label.toString();
            row.essential = essential.contains(pkg);
            row.byPc = reason(p, yt, pkg, info);
            row.override = overrides.get(pkg);
            rows.put(pkg, row);
        }
        List<AppRow> list = new ArrayList<>(rows.values());
        Collections.sort(list, new java.util.Comparator<AppRow>() { @Override public int compare(AppRow a, AppRow b) {
            if (a.blocked() != b.blocked()) return a.blocked() ? -1 : 1;
            return a.label.toLowerCase(Locale.ROOT).compareTo(b.label.toLowerCase(Locale.ROOT));
        }});
        return list;
    }

    Set<String> blockedPackages(Policy p, Store store) {
        Set<String> out = new HashSet<>();
        for (AppRow r : rows(p, store)) if (r.blocked()) out.add(r.pkg);
        return out;
    }

    /** The same list the PC service builds in blocked_domains(), with this phone's YouTube choice applied. */
    List<String> blockedDomains(Policy p, String youtubeOnPhone) {
        Set<String> d = new HashSet<>(p.customBlocked);
        for (String cat : p.webCategories) {
            List<String> list = webDomains.get(cat);
            if (list != null) d.addAll(list);
        }
        List<String> yt = java.util.Arrays.asList("youtube.com", "youtu.be", "youtube-nocookie.com");
        if (youtubeBlocked(p, youtubeOnPhone)) d.addAll(yt);
        else d.removeAll(yt);
        d.removeAll(p.exceptions);
        return new ArrayList<>(d);
    }
}
