# FocusGuard

A self-control blocker for Kubuntu (KDE Plasma), in the spirit of Freedom and Cold Turkey.
While a block is running it:

- **closes blocked applications** (by category: games, media players, chat apps, social media apps, news and feed readers; or any app you tick; or any process name you type; with exceptions for single apps inside a blocked category),
- **blocks websites** by category (social media, games, video and streaming, news, shopping, gambling) plus your own list, with exceptions,
- **filters YouTube video by video**: study videos play, gaming, entertainment and other off-topic videos are replaced by a "blocked" page,
- **turns itself on by schedule** (days of the week and times of day), or on demand as a timed focus session,
- **speaks English or Arabic**: pick the language at the bottom of the window; Arabic uses a right-to-left layout,
- **resists being switched off**: password, an optional strict mode with no way out until the block ends, a self-restarting service, and an uninstaller that needs the service's permission.

## Install

On the Kubuntu machine:

```sh
cd focusguard
sudo ./install.sh
```

This installs Python's PyQt6 package through apt, copies the program to `/opt/focusguard`, and starts the
`focusguard` system service. Open **FocusGuard** from the application menu (or run `focusguard`).
A tray icon starts with your next login.

Upgrading uses the same command. While a strict block is running the installer stops, so that a block cannot be
undone by accident. To upgrade anyway, run `sudo ./install.sh --during-block`: your settings, the block and strict
mode all stay as they are.

### Add the browser extension

Website blocking works in every program through the hosts file without the extension. The extension adds
per-video YouTube filtering, blocking of every subdomain, and a clear "blocked" page.

Kubuntu ships Firefox and Chromium as snaps, which cannot read `/opt`, so first copy the extension into your home:

```sh
cp -r /opt/focusguard/extension ~/focusguard-extension
```

**Chrome, Chromium, Brave, Edge, Vivaldi:** open `chrome://extensions`, turn on *Developer mode*, choose
*Load unpacked*, and pick `~/focusguard-extension/chromium`. It stays installed across restarts.

**Firefox:** release Firefox only installs signed add-ons permanently.
- To try it now: open `about:debugging#/runtime/this-firefox`, *Load Temporary Add-on*, and pick
  `~/focusguard-extension/firefox/manifest.json`. It is removed when Firefox closes.
- To keep it: sign `~/focusguard-extension/focusguard-firefox.xpi` for free at
  <https://addons.mozilla.org/developers/> (choose *On your own* distribution), then open the signed file in Firefox.
  Firefox ESR and Developer Edition can instead set `xpinstall.signatures.required` to `false` in `about:config`
  and install the unsigned `.xpi` directly.

When the extension is running, the *Protection* tab shows "Extension currently running in: …".

## Using it

| Tab | What you set |
| --- | --- |
| Status | See whether blocking is on and until when, start a focus session, see what was closed. |
| Applications | Tick categories and individual apps. Apps in a ticked category are ticked for you; untick one to keep it allowed. Add other process names (for example a Wine game's `.exe`). |
| Websites | Tick categories, add your own sites, list sites that must never be blocked. |
| YouTube | Filter, block completely, or leave alone. Choose allowed video categories and allow/block keywords. |
| Schedule | Time blocks by day of week. An end time before the start time runs past midnight. |
| Protection | Password, strict mode, and the two browser options below. |

**Language.** The *Language* list at the bottom of the window switches between English and العربية at once; the
choice is saved per user in `~/.config/focusguard/gui.json`. Times always use Western digits. The service, the
`focusguardctl` command and the browser extension's blocked page stay in English.

**How YouTube videos are judged.** Each video has a category chosen by its uploader (Education, Gaming, Music…).
A video plays if its category is one you allow. Your keywords are matched against the title, channel name and tags:
a block keyword always blocks, an allow keyword allows a video whatever its category. Because uploaders choose the
category, some videos are mislabelled; use the keyword lists to correct that (for example, add your subjects and
favourite teaching channels to the allow list). Shorts can be blocked outright. The home page, search and
channel pages stay usable.

**Command line.** `focusguardctl status`, `focusguardctl start 50`, `focusguardctl stop`, `focusguardctl set-password`.

## Linking a phone (alpha)

The phone app and the link are **alpha**: partly tested, expect rough edges. See [android/README.md](../android/README.md).

The *Phone* page (or `focusguardctl link`) creates a link code for the FocusGuard Android app. While a phone is
linked, the service sends its schedule, block lists and session times to the phone through the public
[ntfy.sh](https://ntfy.sh) relay, encrypted (AES-256-GCM) with a key derived from the code, so the relay cannot read
them. Nothing is sent until you create a link, and *Unlink* (or `focusguardctl unlink`) stops it. The service only
makes outgoing requests for this; it opens no port. Creating and removing a link need the password and are refused
during a strict block.

## How strong is the protection?

| Level | What stops you |
| --- | --- |
| No password | Nothing; it is a scheduler. |
| Password | Changing settings, ending a session early and uninstalling all need the password. Let a friend set it for a real barrier. |
| Strict mode | During a block nothing can be changed, even with the password, and uninstall is refused. Program files are made immutable until the block ends. |

**Strict mode turned on by mistake?** Outside a block you can simply untick it and apply. During a block, the
administrator can switch it off from a terminal (this is the deliberate `sudo` way out; blocking stays on, only the
lock is removed):

    sudo systemctl stop focusguard-watchdog.timer focusguard.service
    sudo python3 -c "import json; p='/etc/focusguard/config.json'; c=json.load(open(p)); c['protection']['strict']=False; json.dump(c, open(p,'w'), indent=2)"
    sudo systemctl start focusguard.service focusguard-watchdog.timer

Always on: the service runs as root, restarts within a second if killed, a watchdog timer restarts and re-enables
it within 30 seconds if it is stopped or disabled, and edits to the hosts file are undone within seconds.

Browser options on the Protection tab:
- **Close any browser without the extension**: during a block, a browser that has not checked in through the
  extension within about 90 seconds of starting is closed, and browsers the extension does not support (Falkon,
  Konqueror, Tor Browser…) are closed immediately. Without this, YouTube filtering can be sidestepped by using a
  different browser. Turn it on once the extension is installed permanently.
- **Turn off private windows and encrypted DNS**: writes browser policies so private/incognito windows (where
  extensions do not run) and DNS-over-HTTPS (which bypasses the hosts file) are unavailable. Restart the browser after changing it.

**Limits, stated plainly.** You own this computer. Anyone with `sudo` who is determined can still remove any
blocker: for example by stopping both systemd units and deleting the files, booting another system, or changing the
clock. FocusGuard is built to make that slow and deliberate rather than impossible. If you want it to hold against
yourself with `sudo`, the real fix is to have someone else hold the administrator password. Also: a VPN or proxy
app is not detected, videos embedded on other websites are not filtered, and the hosts file cannot block subdomains
that are not listed (the extension does).

## Uninstall

```sh
sudo ./uninstall.sh          # keeps your settings in /etc/focusguard
sudo ./uninstall.sh --purge  # removes them too
```

It asks for the FocusGuard password and is refused while a strict block is running.

## How it is built

```
focusguard/daemon.py   root service: schedule, closing apps, hosts file, browser checks, control socket, HTTP for the extension
focusguard/gui.py      PyQt6 settings app and tray icon
focusguard/i18n.py     interface language; focusguard/lang_ar.py holds the Arabic text
focusguard/cli.py      focusguardctl
focusguard/apps.py     reads .desktop files, recognises processes (native, Flatpak, Snap, Steam, Wine)
focusguard/schedule.py weekly schedule maths
focusguard/system.py   hosts file, browser policies, immutable flags, systemd
focusguard/link.py     phone link: encrypts the state and posts it to the relay (shared with the Android app)
focusguard/data/web_categories.json   the site lists; edit to taste and reinstall
extension/             browser extension (Firefox MV2 and Chromium MV3 builds from one source)
systemd/, desktop/     unit files, menu entry, tray autostart
```

The settings app talks to the service over `/run/focusguard/control.sock`. The extension polls
`http://127.0.0.1:47613`, which only answers browser extensions, not web pages. Settings live in
`/etc/focusguard/config.json`, readable by root only; the password is stored as a salted scrypt hash.

## Tests

```sh
python3 -m unittest tests.test_core          # schedule, settings validation, app matching, hosts file
sudo python3 -m unittest tests.test_integration   # real service in a sandbox directory (touches nothing in /etc)
node tests/test_extension.js                 # YouTube page parsing and block decisions
```

### What has and has not been tested

Tested on a real Kubuntu 26.10 machine (Plasma 6, Wayland) with Firefox Developer Edition, using a stand-in
program and example.org: install and both systemd units, closing a blocked program within about 2 seconds and
leaving others alone, the hosts-file block and its removal, a schedule starting and ending on time, the policy
endpoint refusing web pages, the settings app starting cleanly, and the Firefox extension blocking Gaming, Comedy
and Music videos, a Shorts link and a blocked site while an Education video and the YouTube home page stayed open.
Category reading was checked against 14 live YouTube videos.

Also tested in a container: all three suites above and the Chromium build of the extension in a real Chromium.

**Not yet tested:** killing or stopping the service on a real system (needs sudo), strict mode's immutable-file
step, the browser policy files, Flatpak apps, and real Wine, Lutris and Proton games closing (recognised by their
install folders, checked only with simulated processes). Start without strict mode until you have seen a full
block start and end.
