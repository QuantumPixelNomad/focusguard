package com.focusguard.companion;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.net.ConnectivityManager;
import android.net.LinkProperties;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.VpnService;
import android.os.Build;
import android.os.ParcelFileDescriptor;

import com.focusguard.companion.core.DnsPacket;
import com.focusguard.companion.core.Policy;

import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

/**
 * Website blocking. A local "VPN" that receives only the phone's DNS lookups: names on the block list
 * get an empty answer, everything else is passed on to the network's normal DNS server. No other
 * traffic goes through it and nothing leaves the phone that would not have left anyway.
 */
public class DnsVpnService extends VpnService {
    static final String ACTION_START = "start", ACTION_STOP = "stop";
    private static final String DNS_ADDRESS = "10.111.222.2";
    private static volatile boolean running;
    private static volatile DnsVpnService instance;
    private java.io.FileDescriptor stopRead, stopWrite; // a pipe that wakes the reader so it can exit

    private ParcelFileDescriptor tun;
    private Thread reader;
    private ExecutorService pool;
    private volatile List<InetAddress> upstream = new ArrayList<>();
    private volatile long upstreamAt;

    static boolean running() {
        return running;
    }

    /** Start or stop the filter. Does nothing if it is already in the wanted state. */
    static void set(Context ctx, boolean on) {
        if (on == running) return;
        if (!on) {
            DnsVpnService me = instance;
            if (me != null) {
                me.shutdown();
                me.stopSelf();
            }
            return;
        }
        Intent i = new Intent(ctx, DnsVpnService.class).setAction(ACTION_START);
        try {
            ctx.startService(i);
        } catch (RuntimeException e) {
            try {
                ctx.startForegroundService(i);
            } catch (RuntimeException ignored) {
            }
        }
    }

    @Override
    public void onCreate() {
        super.onCreate();
        instance = this;
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        String action = intent == null ? ACTION_START : intent.getAction();
        if (ACTION_STOP.equals(action)) {
            shutdown();
            stopSelf();
            return START_NOT_STICKY;
        }
        showNotification();
        if (tun == null) {
            Engine engine = Engine.get(this);
            if (!engine.active() || engine.domains().isEmpty() || !open()) {
                shutdown();
                stopSelf();
                return START_NOT_STICKY;
            }
        }
        return START_STICKY;
    }

    private boolean open() {
        try {
            refreshUpstream();
            Builder b = new Builder()
                    .setSession("FocusGuard")
                    .addAddress("10.111.222.1", 32)
                    .addDnsServer(DNS_ADDRESS)
                    .addRoute(DNS_ADDRESS, 32);
            if (Build.VERSION.SDK_INT >= 29) b.setMetered(false);
            tun = b.establish();
            if (tun == null) return false;
            java.io.FileDescriptor[] pipe = android.system.Os.pipe();
            stopRead = pipe[0];
            stopWrite = pipe[1];
        } catch (RuntimeException | android.system.ErrnoException e) {
            return false;
        }
        pool = new ThreadPoolExecutor(2, 24, 30, TimeUnit.SECONDS, new LinkedBlockingQueue<Runnable>(200),
                new ThreadPoolExecutor.DiscardOldestPolicy());
        ((ThreadPoolExecutor) pool).allowCoreThreadTimeOut(true);
        final ParcelFileDescriptor fd = tun;
        final java.io.FileDescriptor stop = stopRead;
        reader = new Thread(new Runnable() { @Override public void run() { loop(fd, stop); } }, "focusguard-dns");
        reader.start();
        running = true;
        return true;
    }

    private void loop(ParcelFileDescriptor fd, java.io.FileDescriptor stop) {
        final FileOutputStream out = new FileOutputStream(fd.getFileDescriptor());
        try (FileInputStream in = new FileInputStream(fd.getFileDescriptor())) {
            byte[] buf = new byte[32767];
            Engine engine = Engine.get(this);
            android.system.StructPollfd tunPoll = new android.system.StructPollfd();
            tunPoll.fd = fd.getFileDescriptor();
            tunPoll.events = (short) android.system.OsConstants.POLLIN;
            android.system.StructPollfd stopPoll = new android.system.StructPollfd();
            stopPoll.fd = stop;
            stopPoll.events = (short) android.system.OsConstants.POLLIN;
            android.system.StructPollfd[] polls = {tunPoll, stopPoll};
            while (true) {
                try {
                    android.system.Os.poll(polls, 30000);
                } catch (android.system.ErrnoException e) {
                    if (e.errno == android.system.OsConstants.EINTR) continue;
                    break;
                }
                if (stopPoll.revents != 0) break;
                if ((tunPoll.revents & android.system.OsConstants.POLLIN) == 0) {
                    if (tunPoll.revents != 0) break; // error or hang-up
                    continue;
                }
                int n = in.read(buf);
                if (n <= 0) continue;
                final DnsPacket.Query q = DnsPacket.parse(buf, n);
                if (q == null) continue;
                if (engine.active() && engine.domains().isBlocked(q.name)) {
                    byte[] answer = DnsPacket.blockedAnswer(q);
                    write(out, DnsPacket.wrapReply(q, answer, answer.length));
                } else {
                    pool.execute(new Runnable() { @Override public void run() { forward(q, out); } });
                }
            }
        } catch (IOException | RuntimeException ignored) {
            // the interface was closed
        }
        try {
            android.system.Os.close(stop);
        } catch (Exception ignored) {
        }
    }

    private static void write(FileOutputStream out, byte[] packet) {
        try {
            synchronized (out) {
                out.write(packet);
            }
        } catch (IOException ignored) {
        }
    }

    private void forward(DnsPacket.Query q, FileOutputStream out) {
        if (System.currentTimeMillis() - upstreamAt > 30000) refreshUpstream();
        byte[] buf = new byte[4096];
        for (InetAddress server : upstream) {
            try (DatagramSocket sock = new DatagramSocket()) {
                protect(sock);
                sock.setSoTimeout(4000);
                sock.send(new DatagramPacket(q.dns, q.dns.length, server, 53));
                DatagramPacket reply = new DatagramPacket(buf, buf.length);
                sock.receive(reply);
                if (reply.getLength() >= 12 && buf[0] == q.dns[0] && buf[1] == q.dns[1]) {
                    write(out, DnsPacket.wrapReply(q, buf, reply.getLength()));
                    return;
                }
            } catch (IOException | RuntimeException ignored) {
            }
        }
        byte[] fail = DnsPacket.failAnswer(q);
        write(out, DnsPacket.wrapReply(q, fail, fail.length));
    }

    /** The DNS servers of the real networks underneath, so lookups keep going where they always went. */
    private void refreshUpstream() {
        List<InetAddress> found = new ArrayList<>();
        try {
            ConnectivityManager cm = (ConnectivityManager) getSystemService(Context.CONNECTIVITY_SERVICE);
            for (Network n : cm.getAllNetworks()) {
                NetworkCapabilities caps = cm.getNetworkCapabilities(n);
                if (caps == null || !caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                        || !caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)) continue;
                LinkProperties lp = cm.getLinkProperties(n);
                if (lp == null) continue;
                for (InetAddress a : lp.getDnsServers()) if (!found.contains(a)) found.add(a);
            }
            for (String fallback : new String[]{"1.1.1.1", "8.8.8.8"}) {
                InetAddress a = InetAddress.getByName(fallback);
                if (!found.contains(a)) found.add(a);
            }
        } catch (Exception ignored) {
        }
        if (found.size() > 4) found = new ArrayList<>(found.subList(0, 4));
        upstream = found;
        upstreamAt = System.currentTimeMillis();
    }

    private void showNotification() {
        try {
            NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
            nm.createNotificationChannel(new NotificationChannel("block", "Blocking status", NotificationManager.IMPORTANCE_LOW));
            Policy.State st = Engine.get(this).state();
            String until = st.untilMs > 0 ? " until " + new SimpleDateFormat("EEE HH:mm", Locale.US).format(new Date(st.untilMs)) : "";
            PendingIntent pi = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class), PendingIntent.FLAG_IMMUTABLE);
            Notification n = new Notification.Builder(this, "block")
                    .setSmallIcon(R.drawable.ic_notify)
                    .setContentTitle("FocusGuard is blocking" + until)
                    .setContentText("Blocked websites and apps are unavailable.")
                    .setOngoing(true)
                    .setContentIntent(pi)
                    .build();
            if (Build.VERSION.SDK_INT >= 34) startForeground(1, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
            else startForeground(1, n);
        } catch (RuntimeException ignored) {
            // without the notification the filter still runs: the system keeps an active VPN alive
        }
    }

    private void shutdown() {
        running = false;
        if (stopWrite != null) {
            try {
                android.system.Os.write(stopWrite, new byte[]{1}, 0, 1);
            } catch (Exception ignored) {
            }
            for (java.io.FileDescriptor f : new java.io.FileDescriptor[]{stopWrite}) {
                try {
                    android.system.Os.close(f);
                } catch (Exception ignored) {
                }
            }
            stopWrite = null; // the reader's end is left to the garbage collector; it is still in use for a moment
        }
        if (tun != null) {
            try {
                tun.close();
            } catch (IOException ignored) {
            }
            tun = null;
        }
        if (pool != null) {
            pool.shutdownNow();
            pool = null;
        }
        try {
            stopForeground(true);
        } catch (RuntimeException ignored) {
        }
    }

    @Override
    public void onRevoke() {
        shutdown();
        stopSelf();
    }

    @Override
    public void onDestroy() {
        shutdown();
        if (instance == this) instance = null;
        super.onDestroy();
    }
}
