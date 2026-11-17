package com.focusguard.companion;

import android.accessibilityservice.AccessibilityService;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.provider.Settings;
import android.view.accessibility.AccessibilityEvent;

/** Watches which app comes to the front and sends blocked ones away while a block is running. */
public class GuardAccessibilityService extends AccessibilityService {
    @Override
    protected void onServiceConnected() {
        Engine.get(this).refresh();
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        if (event == null || event.getEventType() != AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) return;
        CharSequence pkg = event.getPackageName();
        if (pkg == null) return;
        String name = pkg.toString();
        Engine engine = Engine.get(this);
        if (!engine.shouldBlock(name)) return;
        performGlobalAction(GLOBAL_ACTION_HOME);
        Intent i = new Intent(this, BlockedActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_NO_ANIMATION)
                .putExtra(BlockedActivity.EXTRA_PACKAGE, name);
        try {
            startActivity(i);
        } catch (RuntimeException ignored) {
        }
    }

    @Override
    public void onInterrupt() {
    }

    static boolean enabled(Context ctx) {
        String list = Settings.Secure.getString(ctx.getContentResolver(), Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES);
        if (list == null) return false;
        String me = new ComponentName(ctx, GuardAccessibilityService.class).flattenToString();
        String shortMe = new ComponentName(ctx, GuardAccessibilityService.class).flattenToShortString();
        for (String s : list.split(":")) {
            if (s.equalsIgnoreCase(me) || s.equalsIgnoreCase(shortMe)) return true;
        }
        return false;
    }
}
