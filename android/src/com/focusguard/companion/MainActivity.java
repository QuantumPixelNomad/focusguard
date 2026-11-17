package com.focusguard.companion;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.ConnectivityManager;
import android.net.LinkProperties;
import android.net.Network;
import android.net.VpnService;
import android.os.Build;
import android.content.DialogInterface;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.text.InputType;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import com.focusguard.companion.core.Policy;
import com.focusguard.companion.core.Relay;
import com.focusguard.companion.core.Schedule;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

public class MainActivity extends Activity {
    private static final String[] DAYS = {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"};
    private Engine engine;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable update = new Runnable() { @Override public void run() { render(); } };
    private final Runnable ticker = new Runnable() {
        @Override
        public void run() {
            render();
            handler.postDelayed(this, 5000);
        }
    };

    private TextView statusTitle, statusDetail;
    private TextView linkText, appsState, sitesState, dnsWarning, rulesText, schedulesText, youtubeText;
    private EditText codeInput;
    private Button linkButton, appsButton, sitesButton, youtubeButton, chooseApps;
    private LinearLayout linkForm;

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        engine = Engine.get(this);
        int pad = Ui.dp(this, 16);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(pad, pad, pad, pad);

        // Status
        LinearLayout status = Ui.card(this);
        statusTitle = Ui.text(this, "", 24, true);
        statusDetail = Ui.text(this, "", 15, false);
        status.addView(statusTitle);
        status.addView(statusDetail);
        root.addView(status);

        // Link
        LinearLayout link = Ui.card(this);
        link.addView(Ui.text(this, "Link to your PC", 17, true));
        linkText = Ui.text(this, "", 15, false);
        link.addView(linkText);
        linkForm = new LinearLayout(this);
        linkForm.setOrientation(LinearLayout.VERTICAL);
        codeInput = new EditText(this);
        codeInput.setHint("XXXX-XXXX-XXXX-XXXX");
        codeInput.setSingleLine(true);
        codeInput.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS
                | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS | InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD);
        codeInput.setTextDirection(View.TEXT_DIRECTION_LTR);
        linkForm.addView(codeInput);
        link.addView(linkForm);
        linkButton = button("Link", new View.OnClickListener() { @Override public void onClick(View v) { onLinkButton(); } });
        link.addView(linkButton);
        root.addView(link);

        // Permissions
        LinearLayout setup = Ui.card(this);
        setup.addView(Ui.text(this, "What this phone may block", 17, true));
        appsState = Ui.text(this, "", 15, false);
        setup.addView(appsState);
        appsButton = button("Turn on app blocking", new View.OnClickListener() { @Override public void onClick(View v) { openAccessibility(); } });
        setup.addView(appsButton);
        sitesState = Ui.text(this, "", 15, false);
        sitesState.setPadding(0, Ui.dp(this, 10), 0, 0);
        setup.addView(sitesState);
        sitesButton = button("Allow website blocking", new View.OnClickListener() { @Override public void onClick(View v) { askVpn(); } });
        setup.addView(sitesButton);
        dnsWarning = Ui.text(this, "", 14, false);
        setup.addView(dnsWarning);
        root.addView(setup);

        // Rules
        LinearLayout rules = Ui.card(this);
        rules.addView(Ui.text(this, "Rules from your PC", 17, true));
        rulesText = Ui.text(this, "", 15, false);
        rules.addView(rulesText);
        chooseApps = button("Choose apps on this phone", new View.OnClickListener() { @Override public void onClick(View v) { startActivity(new Intent(MainActivity.this, AppsActivity.class)); } });
        rules.addView(chooseApps);
        youtubeText = Ui.text(this, "", 15, false);
        youtubeText.setPadding(0, Ui.dp(this, 10), 0, 0);
        rules.addView(youtubeText);
        youtubeButton = button("", new View.OnClickListener() { @Override public void onClick(View v) { toggleYoutube(); } });
        rules.addView(youtubeButton);
        root.addView(rules);

        // Schedule
        LinearLayout sched = Ui.card(this);
        sched.addView(Ui.text(this, "Schedule", 17, true));
        schedulesText = Ui.text(this, "", 15, false);
        sched.addView(schedulesText);
        root.addView(sched);

        ScrollView scroll = new ScrollView(this);
        scroll.addView(root);
        setContentView(scroll);

        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 1);
        }
    }

    private Button button(String label, View.OnClickListener l) {
        Button b = new Button(this);
        b.setText(label);
        b.setAllCaps(false);
        b.setOnClickListener(l);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        lp.topMargin = Ui.dp(this, 6);
        b.setLayoutParams(lp);
        return b;
    }

    @Override
    protected void onResume() {
        super.onResume();
        engine.addListener(update);
        engine.refresh();
        handler.post(ticker);
    }

    @Override
    protected void onPause() {
        super.onPause();
        engine.removeListener(update);
        handler.removeCallbacks(ticker);
    }

    // ---- actions ---------------------------------------------------------------
    private void onLinkButton() {
        if (engine.linked()) {
            if (engine.active()) {
                toast("A block is running. You can unlink when it ends.");
                return;
            }
            new AlertDialog.Builder(this)
                    .setTitle("Unlink from the PC?")
                    .setMessage("This phone will stop following the PC's blocks and schedule.")
                    .setPositiveButton("Unlink", new DialogInterface.OnClickListener() { @Override public void onClick(DialogInterface d, int w) { engine.unlink(); } })
                    .setNegativeButton("Cancel", null)
                    .show();
            return;
        }
        String code = Relay.normalizeCode(codeInput.getText().toString());
        if (code == null) {
            toast("That is not a complete link code. It has 16 letters and digits.");
            return;
        }
        codeInput.setText("");
        engine.link(code, Relay.DEFAULT_SERVER);
    }

    private void openAccessibility() {
        new AlertDialog.Builder(this)
                .setTitle("Turn on app blocking")
                .setMessage("On the next screen, open \"FocusGuard\" under installed or downloaded apps and switch it on.\n\n"
                        + "If Android says the setting is restricted: open Settings, Apps, FocusGuard, tap the three dots "
                        + "at the top right, choose \"Allow restricted settings\", then come back and try again.\n\n"
                        + "FocusGuard only looks at which app is on screen.")
                .setPositiveButton("Continue", new DialogInterface.OnClickListener() { @Override public void onClick(DialogInterface d, int w) {
                    try {
                        startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS));
                    } catch (RuntimeException e) {
                        toast("Open Settings, Accessibility yourself and turn on FocusGuard.");
                    }
                }})
                .setNegativeButton("Cancel", null)
                .show();
    }

    private void askVpn() {
        Intent i = VpnService.prepare(this);
        if (i == null) {
            engine.refresh();
            return;
        }
        try {
            startActivityForResult(i, 2);
        } catch (RuntimeException e) {
            toast("This phone did not show the permission question.");
        }
    }

    @Override
    protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        engine.refresh();
    }

    private void toggleYoutube() {
        boolean blocking = Store.BLOCK.equals(engine.store.youtubeOnPhone());
        if (blocking && engine.active()) {
            toast("A block is running. You can change this when it ends.");
            return;
        }
        engine.store.setYoutubeOnPhone(blocking ? Store.ALLOW : Store.BLOCK);
        engine.rulesChanged();
    }

    private void toast(String s) {
        Toast.makeText(this, s, Toast.LENGTH_LONG).show();
    }

    // ---- display ---------------------------------------------------------------
    private void render() {
        Policy p = engine.policy();
        Policy.State st = engine.state();
        boolean linked = engine.linked();

        if (!linked) {
            statusTitle.setText("Not linked yet");
            statusDetail.setText("Enter the link code from the FocusGuard app on your PC.");
        } else if (p == null) {
            statusTitle.setText("Waiting for your PC");
            statusDetail.setText("Nothing has arrived yet. Check that the PC is on and the code is the one shown on its Phone page.");
        } else if (st.active) {
            statusTitle.setText("Blocking is ON");
            statusDetail.setText("Until " + Ui.time(st.untilMs) + " (" + st.reason + ").");
        } else {
            statusTitle.setText("Blocking is off");
            statusDetail.setText(st.nextStartMs > 0 ? "Next scheduled block: " + Ui.time(st.nextStartMs) + "." : "Nothing is scheduled.");
        }

        linkForm.setVisibility(linked ? View.GONE : View.VISIBLE);
        linkButton.setText(linked ? "Unlink" : "Link");
        if (!linked) {
            linkText.setText("On the PC, open FocusGuard, go to Phone and choose \"Link a phone\". Type the code it shows here.");
        } else {
            StringBuilder sb = new StringBuilder();
            sb.append(p == null ? "Linked." : "Linked to " + (p.pcName.isEmpty() ? "your PC" : p.pcName) + ".");
            if (p != null) sb.append(" Rules last changed or confirmed ").append(Ui.time((long) (p.pcNow * 1000))).append(".");
            if (engine.relayConnected) sb.append("\nConnected to the relay.");
            else if (engine.relayError != null) sb.append("\nCannot reach the relay right now: ").append(engine.relayError);
            linkText.setText(sb.toString());
        }

        boolean acc = GuardAccessibilityService.enabled(this);
        appsState.setText(acc ? "App blocking is on." : "App blocking is off. Blocked apps will still open.");
        appsButton.setVisibility(acc ? View.GONE : View.VISIBLE);
        boolean vpn = VpnService.prepare(this) == null;
        sitesState.setText(vpn ? (DnsVpnService.running() ? "Website blocking is running." : "Website blocking is allowed. It runs only during a block.")
                : "Website blocking is not allowed yet. Blocked sites will still open.");
        sitesButton.setVisibility(vpn ? View.GONE : View.VISIBLE);
        String privateDns = privateDnsName();
        dnsWarning.setVisibility(privateDns == null ? View.GONE : View.VISIBLE);
        if (privateDns != null) {
            dnsWarning.setText("Private DNS is set to " + privateDns + ", which bypasses website blocking. "
                    + "In Settings, Network, Private DNS, choose Off or Automatic.");
        }

        if (p == null) {
            rulesText.setText("No rules received yet.");
            schedulesText.setText("No schedule received yet.");
            youtubeText.setVisibility(View.GONE);
            youtubeButton.setVisibility(View.GONE);
            chooseApps.setVisibility(View.GONE);
            return;
        }
        chooseApps.setVisibility(View.VISIBLE);
        List<String> cats = new ArrayList<>();
        for (String c : new String[]{"games", "media", "chat"}) {
            if (p.appCategories.contains(c)) cats.add(c.equals("media") ? "media players" : c.equals("chat") ? "social and chat" : c);
        }
        List<String> web = new ArrayList<>();
        for (String c : p.webCategories) {
            String label = engine.rules.webLabels.get(c);
            web.add(label == null ? c : label.toLowerCase(Locale.US));
        }
        java.util.Collections.sort(web);
        String rules = "App categories: " + (cats.isEmpty() ? "none" : join(cats)) + ".\n"
                + "Website categories: " + (web.isEmpty() ? "none" : join(web)) + ".\n"
                + "Your own blocked sites: " + p.customBlocked.size() + ". Sites never blocked: " + p.exceptions.size() + ".\n"
                + "On this phone that comes to " + engine.blockedAppCount() + " apps and " + engine.domains().size() + " sites."
                + (p.strict ? "\nStrict mode is on at the PC." : "");
        rulesText.setText(rules);

        boolean filter = "filter".equals(p.youtubeMode);
        youtubeText.setVisibility(View.VISIBLE);
        youtubeButton.setVisibility(filter ? View.VISIBLE : View.GONE);
        if (filter) {
            boolean blocking = Store.BLOCK.equals(engine.store.youtubeOnPhone());
            youtubeText.setText("YouTube: the PC filters video by video, which a phone cannot do inside the YouTube app. "
                    + "During a block this phone " + (blocking ? "blocks YouTube completely." : "leaves YouTube open."));
            youtubeButton.setText(blocking ? "Leave YouTube open instead" : "Block YouTube instead");
        } else {
            youtubeText.setText("block".equals(p.youtubeMode) ? "YouTube: blocked during a block, as on the PC." : "YouTube: not blocked, as on the PC.");
        }

        StringBuilder sb = new StringBuilder();
        for (Schedule.Entry e : p.schedules) {
            if (sb.length() > 0) sb.append('\n');
            List<String> days = new ArrayList<>();
            for (int d = 0; d < 7; d++) if (e.days[d]) days.add(DAYS[d]);
            sb.append(days.isEmpty() ? "No days" : join(days)).append("  ")
                    .append(hm(e.start)).append(" to ").append(hm(e.end));
            if (!e.name.isEmpty()) sb.append("  ").append(e.name);
            if (!e.enabled) sb.append("  (off)");
        }
        schedulesText.setText(sb.length() == 0 ? "No schedule is set on the PC." : sb.toString());
    }

    private static String hm(int minutes) {
        return String.format(Locale.US, "%02d:%02d", minutes / 60, minutes % 60);
    }

    private static String join(List<String> items) {
        StringBuilder sb = new StringBuilder();
        for (String s : items) {
            if (sb.length() > 0) sb.append(", ");
            sb.append(s);
        }
        return sb.toString();
    }

    /** The Private DNS host name if one is forced, which sends lookups past the website filter. */
    private String privateDnsName() {
        try {
            ConnectivityManager cm = (ConnectivityManager) getSystemService(Context.CONNECTIVITY_SERVICE);
            for (Network n : cm.getAllNetworks()) {
                LinkProperties lp = cm.getLinkProperties(n);
                if (lp != null && lp.getPrivateDnsServerName() != null) return lp.getPrivateDnsServerName();
            }
        } catch (RuntimeException ignored) {
        }
        return null;
    }
}
