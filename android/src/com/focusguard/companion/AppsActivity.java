package com.focusguard.companion;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.DialogInterface;
import android.os.Bundle;
import android.view.View;
import android.view.ViewGroup;
import android.widget.BaseAdapter;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.TextView;
import android.widget.Toast;

import java.util.ArrayList;
import java.util.List;

/** Lists the apps on this phone and lets each one be always blocked, never blocked, or left to the PC's rules. */
public class AppsActivity extends Activity {
    private Engine engine;
    private List<AppRules.AppRow> rows = new ArrayList<>();
    private final BaseAdapter adapter = new BaseAdapter() {
        @Override
        public int getCount() {
            return rows.size();
        }

        @Override
        public Object getItem(int i) {
            return rows.get(i);
        }

        @Override
        public long getItemId(int i) {
            return i;
        }

        @Override
        public View getView(int i, View reuse, ViewGroup parent) {
            LinearLayout box = (LinearLayout) reuse;
            if (box == null) {
                box = new LinearLayout(AppsActivity.this);
                box.setOrientation(LinearLayout.VERTICAL);
                int pad = Ui.dp(AppsActivity.this, 16);
                box.setPadding(pad, pad * 3 / 4, pad, pad * 3 / 4);
                box.addView(Ui.text(AppsActivity.this, "", 16, true));
                box.addView(Ui.text(AppsActivity.this, "", 14, false));
            }
            AppRules.AppRow r = rows.get(i);
            ((TextView) box.getChildAt(0)).setText(r.label);
            ((TextView) box.getChildAt(1)).setText(describe(r));
            return box;
        }
    };

    private static String describe(AppRules.AppRow r) {
        if (r.essential) return "Never blocked (needed to use the phone)";
        if (Store.BLOCK.equals(r.override)) return "Blocked: your choice on this phone";
        if (Store.ALLOW.equals(r.override)) return "Not blocked: your choice on this phone";
        return r.byPc != null ? "Blocked: " + r.byPc + " on the PC" : "Not blocked";
    }

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        engine = Engine.get(this);
        ListView list = new ListView(this);
        list.setAdapter(adapter);
        list.setOnItemClickListener(new android.widget.AdapterView.OnItemClickListener() { @Override public void onItemClick(android.widget.AdapterView<?> parent, View view, int position, long id) { choose(rows.get(position)); } });
        setContentView(list);
    }

    @Override
    protected void onResume() {
        super.onResume();
        reload();
    }

    private void reload() {
        rows = engine.rules.rows(engine.policy(), engine.store);
        adapter.notifyDataSetChanged();
    }

    private void choose(AppRules.AppRow r) {
        if (r.essential) return;
        String follow = "Follow the PC's rules (" + (r.byPc != null ? "blocked" : "not blocked") + ")";
        String[] items = {follow, "Always block during a block", "Never block"};
        int current = r.override == null ? 0 : Store.BLOCK.equals(r.override) ? 1 : 2;
        new AlertDialog.Builder(this)
                .setTitle(r.label)
                .setSingleChoiceItems(items, current, new DialogInterface.OnClickListener() { @Override public void onClick(DialogInterface d, int which) {
                    d.dismiss();
                    String value = which == 0 ? null : which == 1 ? Store.BLOCK : Store.ALLOW;
                    boolean after = value == null ? r.byPc != null : Store.BLOCK.equals(value);
                    if (r.blocked() && !after && engine.active()) {
                        Toast.makeText(AppsActivity.this, "A block is running. You can unblock apps when it ends.", Toast.LENGTH_LONG).show();
                        return;
                    }
                    engine.store.setOverride(r.pkg, value);
                    engine.rulesChanged();
                    reload();
                }})
                .setNegativeButton("Cancel", null)
                .show();
    }
}
