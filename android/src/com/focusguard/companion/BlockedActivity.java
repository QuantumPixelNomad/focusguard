package com.focusguard.companion;

import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

import com.focusguard.companion.core.Policy;

/** Shown in place of a blocked app. */
public class BlockedActivity extends Activity {
    static final String EXTRA_PACKAGE = "package";
    private TextView title, detail;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setGravity(Gravity.CENTER);
        int pad = Ui.dp(this, 32);
        box.setPadding(pad, pad, pad, pad);
        title = Ui.text(this, "", 24, true);
        title.setGravity(Gravity.CENTER);
        detail = Ui.text(this, "", 16, false);
        detail.setGravity(Gravity.CENTER);
        detail.setPadding(0, Ui.dp(this, 12), 0, Ui.dp(this, 28));
        Button ok = new Button(this);
        ok.setText("OK");
        ok.setOnClickListener(new View.OnClickListener() { @Override public void onClick(View v) { goHome(); } });
        box.addView(title);
        box.addView(detail);
        box.addView(ok, new LinearLayout.LayoutParams(Ui.dp(this, 160), LinearLayout.LayoutParams.WRAP_CONTENT));
        setContentView(box);
        show(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        show(intent);
    }

    private void show(Intent intent) {
        String pkg = intent == null ? null : intent.getStringExtra(EXTRA_PACKAGE);
        String name = "This app";
        if (pkg != null) {
            try {
                PackageManager pm = getPackageManager();
                name = pm.getApplicationLabel(pm.getApplicationInfo(pkg, 0)).toString();
            } catch (PackageManager.NameNotFoundException | RuntimeException ignored) {
            }
        }
        Policy.State st = Engine.get(this).state();
        title.setText(name + " is blocked");
        detail.setText(st.active ? "FocusGuard is blocking until " + Ui.time(st.untilMs) + "." : "The block has ended.");
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (!Engine.get(this).active()) finish();
    }

    @Override
    public void onBackPressed() {
        goHome();
    }

    private void goHome() {
        startActivity(new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        finish();
    }
}
