package com.focusguard.companion;

import android.app.Application;

public class App extends Application {
    @Override
    public void onCreate() {
        super.onCreate();
        Engine.get(this);
    }
}
