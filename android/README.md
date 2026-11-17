# FocusGuard for Android (alpha)

> **Alpha.** The phone app and the PC-to-phone link are an early, partly tested version. The author has tried
> them on a real phone, but not every part, so expect rough edges. The PC app does not need the phone app.

The phone companion to FocusGuard on your Kubuntu PC. It follows the PC: when a block is running there
(a schedule or a focus session), the same block runs on the phone.

## What it does

- **Follows the PC automatically.** The PC publishes its schedule, categories and any running focus session.
  The phone picks changes up within a second or two while its screen is on, over Wi-Fi or mobile data.
- **Keeps the schedule on the phone.** Schedules keep working when the phone is offline or the PC is off.
  Only a session started by hand on the PC needs the phone to be online to hear about it.
- **Blocks apps.** A blocked app is closed as soon as it opens and a "blocked" screen is shown.
  The PC's categories are mapped to phone apps: Games, media players, social and chat, plus the apps
  behind the PC's website categories (Instagram for social media, Netflix for video, and so on).
  On the *Choose apps on this phone* screen every app can be set to always block, never block, or follow the PC.
- **Blocks websites** in every browser and app, using the same site lists as the PC, your own blocked
  sites and your exceptions.
- **YouTube.** The PC filters YouTube video by video. That cannot be done inside the YouTube app, so when the
  PC is set to filter, the phone blocks YouTube completely during a block (you can switch that to "leave open").

## Set it up

1. **PC:** install FocusGuard 0.2.0 or newer (`sudo ./install.sh`), open it, go to **Phone**, choose
   **Link a phone**. It shows a 16-character code.
2. **Phone:** build the APK (see *Build* below) or take it from the repository's Releases page if one is published, copy it to the phone and open it. Android asks you to allow
   installing from that source; allow it. Play Protect may warn that it does not know the app.
3. Open FocusGuard on the phone and type the code under **Link to your PC**.
4. Tap **Turn on app blocking** and switch FocusGuard on in Accessibility.
   On Android 13 and newer the switch is greyed out at first for apps installed from a file:
   open Settings, Apps, FocusGuard, tap the three dots at the top right, choose **Allow restricted settings**,
   then go back to Accessibility.
5. Tap **Allow website blocking** and accept the connection request. A key icon shows while a block is running.
6. Recommended: in Settings, Apps, FocusGuard, Battery, choose **Unrestricted**, so the phone maker's battery
   saver does not stop it.
7. Open **Choose apps on this phone** and check the list. Mark anything you need as *Never block*.

## How the link works, and privacy

The PC posts its state to a topic on the free public relay <https://ntfy.sh>; the phone reads that topic.
No account is needed. The topic name and the encryption key both come from the link code, so:

- the state is encrypted (AES-256-GCM) before it leaves the PC and only a device with the code can read it;
- the relay sees an unguessable topic name, encrypted bytes, and both devices' IP addresses, nothing else;
- anyone who gets the code could read your schedule and site lists and could post fake states, so treat it
  like a password. *Unlink* on the PC and link again to get a new one.

The relay is a free service run by someone else. If it is down or changes its terms, schedules keep working
and only PC-started sessions stop reaching the phone. The PC re-posts its state every 3 hours because the
relay keeps messages for 12 hours.

The website filter is a local VPN that receives only DNS lookups. Blocked names get an empty answer; all other
lookups go to your network's usual DNS server. No other traffic passes through it and nothing is sent anywhere new.

## Limits, stated plainly

- **It is easy to switch off.** Android lets you turn off the accessibility service or the VPN, or uninstall the
  app, at any time. The app refuses to unlink or unblock apps while a block is running, but it cannot stop you in
  Android's own settings. Strict mode on the PC does not make the phone strict.
- Only one VPN can run on Android at a time. With another VPN app on, website blocking is off.
- If **Private DNS** is set to a provider name, lookups bypass the filter. The app warns about this; choose
  Off or Automatic. A browser's own "secure DNS" setting set to a named provider has the same effect.
- Sites already open in a browser may keep working for a minute or so after a block starts, until the
  browser looks the name up again.
- App categories depend on what each app declares to Android plus a built-in list of well-known apps.
  Check the app list once.
- PC app choices (individual Linux programs) have no meaning on a phone and are not sent.
- Both devices' clocks must be right (automatic time). Schedules use the phone's own time zone.

## What has and has not been tested

Tried by the author on a real phone, but not fully. Tested in a build container:

- The phone's schedule maths against the PC's own `schedule.py` on 3,000 random schedules and times: identical.
- Decryption and reassembly of messages made by the PC's `link.py`, including multi-part ones, a wrong code,
  and tampered messages.
- End to end with the real FocusGuard 0.2.0 service in a sandbox, a stand-in relay that speaks ntfy's
  protocol, and the phone's relay and rules code on a desktop Java runtime: starting a session on the PC
  reached the phone code in under a second, as did stopping it and changing categories.
- DNS packet parsing and answers, including 20,000 damaged packets.
- The APK builds, is signed and passes `apksigner verify`.

**Not yet checked thoroughly on a phone:** every screen, app blocking through accessibility, the website filter
on a real network, start after reboot, behaviour under battery savers, and long-term use of the real ntfy.sh
relay. Expect bugs.

## Build

No Gradle or Android Studio needed. On Ubuntu:

```sh
sudo apt install default-jdk aapt apksigner zipalign dalvik-exchange
ANDROID_JAR=/path/to/android.jar ./build.sh      # an API 34 platform jar
```

The APK has to be signed. `build.sh` uses `focusguard-release.jks` in this folder, or the file named by
`KEYSTORE`, and creates it if it does not exist; set `KEYPASS` to its password. The keystore is not part of
this repository. Keep your own copy safe and private: Android only installs an update over an existing app if
it is signed with the same key, and anyone holding the key could sign a fake update.

```sh
KEYPASS='a password you choose' ANDROID_JAR=/path/to/android.jar ./build.sh
```

Tests: `python3 test/make_vectors.py <focusguard source> build/test/vectors.json`, then compile and run
`test/CoreTest.java`; `test/e2e.sh` runs the end-to-end check.

```
src/.../core/     schedule, policy, relay and DNS logic with no Android dependencies (testable on a PC)
src/.../Engine    holds the rules, decides if a block is running, keeps the relay connection
GuardAccessibilityService   closes blocked apps        DnsVpnService   website filter
MainActivity, AppsActivity, BlockedActivity            the three screens
pc-side/link.py   the PC half of the link, shipped inside FocusGuard as focusguard/link.py
```
