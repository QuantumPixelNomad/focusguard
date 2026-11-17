package com.focusguard.companion;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** Starting the process is enough: App.onCreate starts the engine, which applies the stored rules. */
public class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        Engine.get(context).refresh();
    }
}
