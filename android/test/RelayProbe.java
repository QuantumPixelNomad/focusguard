import com.focusguard.companion.core.*;
import java.time.ZoneId;

/** Runs the phone's relay code on a desktop JVM and prints what the phone would conclude. */
public class RelayProbe {
    public static void main(String[] a) throws Exception {
        final long start = System.currentTimeMillis();
        final Relay.Stream s = new Relay.Stream(a[0], Relay.normalizeCode(a[1]));
        final boolean keep = a.length > 2;
        if (keep) new Thread(new Runnable() { public void run() {
            try { Thread.sleep(Long.parseLong(a[2]) * 1000); } catch (InterruptedException e) { }
            s.close();
        } }).start();
        final double[] newest = {0};
        try {
            s.run(keep, new Relay.Listener() {
                public void onConnected() { System.out.println("connected"); }
                public void onState(String json) {
                    try {
                        Policy p = Policy.parse(json, System.currentTimeMillis());
                        if (p.pcNow <= newest[0]) return;
                        newest[0] = p.pcNow;
                        Policy.State st = p.state(System.currentTimeMillis(), ZoneId.systemDefault());
                        System.out.printf("t=%.1fs STATE active=%b reason=%s minutes_left=%d schedules=%d web=%s apps=%s custom=%d yt=%s delay=%.1fs%n",
                            (System.currentTimeMillis() - start) / 1000.0, st.active, st.reason,
                            st.untilMs == 0 ? 0 : Math.round((st.untilMs - System.currentTimeMillis()) / 60000.0),
                            p.schedules.size(), new java.util.TreeSet<>(p.webCategories), p.appCategories, p.customBlocked.size(), p.youtubeMode,
                            System.currentTimeMillis() / 1000.0 - p.pcNow);
                        System.out.flush();
                    } catch (Exception e) { System.out.println("bad state " + e); }
                }
            });
        } catch (java.io.IOException e) { System.out.println("ended: " + e.getMessage()); }
    }
}
