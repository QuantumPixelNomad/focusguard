package com.focusguard.companion;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.net.VpnService;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;

import com.focusguard.companion.core.DomainSet;
import com.focusguard.companion.core.Policy;
import com.focusguard.companion.core.Relay;

import java.time.ZoneId;
import java.util.Collections;
import java.util.Set;
import java.util.concurrent.CopyOnWriteArrayList;

/**
 * The one long-lived object of the app. Holds the rules received from the PC, decides whether a block
 * is running, keeps the relay connection open while the screen is on, and starts or stops the website filter.
 */
final class Engine {
    private static final long TICK_MS = 20000;
    // Only the system sends the broadcasts we listen for; Android 14 wants that said explicitly.
    private static final int RECEIVER_FLAGS = android.os.Build.VERSION.SDK_INT >= 33 ? Context.RECEIVER_NOT_EXPORTED : 0;
    private static Engine instance;

    static synchronized Engine get(Context ctx) {
        if (instance == null) instance = new Engine(ctx.getApplicationContext());
        return instance;
    }

    final Context ctx;
    final Store store;
    final AppRules rules;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final CopyOnWriteArrayList<Runnable> listeners = new CopyOnWriteArrayList<>();

    private volatile Policy policy;
    private volatile Set<String> blockedPackages = Collections.emptySet();
    private volatile DomainSet domains = new DomainSet(Collections.<String>emptyList(), Collections.<String>emptyList());
    private long packagesAt;

    private Thread relayThread;
    private volatile Relay.Stream stream;
    private volatile int relayGeneration;
    volatile boolean relayConnected;
    volatile String relayError;
    volatile long lastContactMs;

    private Engine(Context ctx) {
        this.ctx = ctx;
        this.store = new Store(ctx);
        this.rules = new AppRules(ctx);
        String json = store.policyJson();
        if (json != null) {
            try {
                policy = Policy.parse(json, store.policyAt());
            } catch (Exception ignored) {
            }
        }
        IntentFilter f = new IntentFilter();
        f.addAction(Intent.ACTION_SCREEN_ON);
        f.addAction(Intent.ACTION_SCREEN_OFF);
        f.addAction(Intent.ACTION_USER_PRESENT);
        f.addAction(Intent.ACTION_TIME_CHANGED);
        f.addAction(Intent.ACTION_TIMEZONE_CHANGED);
        ctx.registerReceiver(new BroadcastReceiver() {
            @Override
            public void onReceive(Context c, Intent i) {
                refresh();
            }
        }, f, RECEIVER_FLAGS);
        IntentFilter pf = new IntentFilter();
        pf.addAction(Intent.ACTION_PACKAGE_ADDED);
        pf.addAction(Intent.ACTION_PACKAGE_REMOVED);
        pf.addDataScheme("package");
        ctx.registerReceiver(new BroadcastReceiver() {
            @Override
            public void onReceive(Context c, Intent i) {
                rulesChanged();
            }
        }, pf, RECEIVER_FLAGS);
        rebuild();
        main.post(tick);
    }

    private final Runnable tick = new Runnable() {
        @Override
        public void run() {
            main.removeCallbacks(this);
            try {
                apply();
            } catch (RuntimeException ignored) {
            }
            main.postDelayed(this, TICK_MS);
        }
    };

    // ---- reading the state ---------------------------------------------------
    Policy policy() {
        return policy;
    }

    boolean linked() {
        return store.code() != null;
    }

    Policy.State state() {
        Policy p = policy;
        if (p == null || !linked()) return new Policy.State();
        return p.state(System.currentTimeMillis(), ZoneId.systemDefault());
    }

    boolean active() {
        return state().active;
    }

    /** True if this app must not stay on screen right now. Called for every window change, so it is cheap. */
    boolean shouldBlock(String pkg) {
        return pkg != null && blockedPackages.contains(pkg) && active();
    }

    DomainSet domains() {
        return domains;
    }

    int blockedAppCount() {
        return blockedPackages.size();
    }

    void addListener(Runnable r) {
        listeners.add(r);
    }

    void removeListener(Runnable r) {
        listeners.remove(r);
    }

    private void changed() {
        main.post(new Runnable() { @Override public void run() {
            for (Runnable r : listeners) r.run();
        }});
    }

    // ---- changing the state --------------------------------------------------
    /** Re-check everything soon, on the main thread. Safe to call from anywhere. */
    void refresh() {
        main.post(tick);
    }

    /** Phone-side choices changed (app list, YouTube option). */
    void rulesChanged() {
        main.post(new Runnable() { @Override public void run() {
            rebuild();
            apply();
            changed();
        }});
    }

    private void rebuild() {
        Policy p = policy;
        if (p == null || !linked()) {
            blockedPackages = Collections.emptySet();
            domains = new DomainSet(Collections.<String>emptyList(), Collections.<String>emptyList());
        } else {
            try {
                blockedPackages = rules.blockedPackages(p, store);
            } catch (RuntimeException ignored) {
            }
            domains = new DomainSet(rules.blockedDomains(p, store.youtubeOnPhone()), p.exceptions);
        }
        packagesAt = System.currentTimeMillis();
    }

    void link(String code, String server) {
        store.clearLink();
        store.setLink(code, server);
        policy = null;
        lastContactMs = 0;
        relayError = null;
        stopRelay();
        rulesChanged();
    }

    void unlink() {
        store.clearLink();
        policy = null;
        stopRelay();
        rulesChanged();
    }

    private void accept(String json) {
        long now = System.currentTimeMillis();
        Policy p;
        try {
            p = Policy.parse(json, now);
        } catch (Exception e) {
            return;
        }
        Policy cur = policy;
        if (cur != null && p.pcNow <= cur.pcNow) return; // an older or repeated message
        policy = p;
        store.setPolicy(json, now);
        rulesChanged();
    }

    private void apply() {
        if (System.currentTimeMillis() - packagesAt > 10 * 60 * 1000) rebuild();
        boolean active = active();
        boolean wantVpn = active && !domains.isEmpty() && VpnService.prepare(ctx) == null;
        DnsVpnService.set(ctx, wantVpn);
        PowerManager pm = (PowerManager) ctx.getSystemService(Context.POWER_SERVICE);
        boolean screenOn = pm == null || pm.isInteractive();
        if (linked() && screenOn) startRelay();
        else stopRelay();
        changed();
    }

    // ---- relay ---------------------------------------------------------------
    private synchronized void startRelay() {
        if (relayThread != null && relayThread.isAlive()) return;
        final int gen = ++relayGeneration;
        final String code = store.code(), server = store.server();
        relayThread = new Thread(new Runnable() { @Override public void run() {
            long wait = 3000;
            while (gen == relayGeneration) {
                Relay.Stream s = new Relay.Stream(server, code);
                stream = s;
                try {
                    s.run(true, new Relay.Listener() {
                        @Override
                        public void onState(String json) {
                            if (gen == relayGeneration) accept(json);
                        }

                        @Override
                        public void onConnected() {
                            relayConnected = true;
                            relayError = null;
                            lastContactMs = System.currentTimeMillis();
                            changed();
                        }
                    });
                    wait = 3000;
                } catch (Exception e) {
                    if (gen == relayGeneration) relayError = e.getMessage() == null ? e.toString() : e.getMessage();
                    wait = Math.min(wait * 2, 60000);
                }
                relayConnected = false;
                changed();
                if (gen != relayGeneration) break;
                try {
                    Thread.sleep(wait);
                } catch (InterruptedException e) {
                    break;
                }
            }
        }}, "focusguard-relay");
        relayThread.setDaemon(true);
        relayThread.start();
    }

    private synchronized void stopRelay() {
        relayGeneration++;
        Relay.Stream s = stream;
        stream = null;
        if (s != null) s.close();
        if (relayThread != null) relayThread.interrupt();
        relayThread = null;
        relayConnected = false;
    }
}
