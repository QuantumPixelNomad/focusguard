"""Installed application discovery (.desktop files) and process matching."""
from __future__ import annotations

import glob
import os
import shlex

DESKTOP_DIRS = [
    "/usr/share/applications",
    "/usr/local/share/applications",
    "/var/lib/flatpak/exports/share/applications",
    "/var/lib/snapd/desktop/applications",
]
USER_DESKTOP_DIRS = [
    ".local/share/applications",
    ".local/share/flatpak/exports/share/applications",
]

# Programs that are launchers or runtimes, never the app itself.
INTERPRETERS = ("python", "bash", "sh", "dash", "zsh", "perl", "ruby", "node", "java", "mono",
                "env", "electron", "wine", "wine64", "wine-preloader", "wine64-preloader", "proton", "flatpak", "snap", "gtk-launch", "kstart", "xdg-open", "sudo", "pkexec")
# Never close these, whatever the configuration says.
PROTECTED = {"systemd", "plasmashell", "kwin_x11", "kwin_wayland", "sddm", "xorg", "xwayland",
             "dbus-daemon", "dbus-broker", "ksmserver", "kded5", "kded6", "startplasma-x11",
             "startplasma-wayland", "pipewire", "wireplumber", "pulseaudio", "focusguard",
             "focusguardctl", "focusguardd", "systemsettings", "polkit-kde-authentication-agent-1"}

DESKTOP_CATEGORY_HINTS = {
    "games": {"game"},
    "media": {"player", "tv"},
    "chat": {"instantmessaging", "chat", "ircclient"},
    "social": set(),  # freedesktop has no "social media" category; recognised by name only
    "news": {"news", "feed"},
}
KNOWN_NAMES = {
    "games": {"steam", "steamwebhelper", "lutris", "heroic", "minecraft-launcher", "prismlauncher",
              "retroarch", "dolphin-emu", "pcsx2", "pcsx2-qt", "rpcs3", "yuzu", "ryujinx", "citra",
              "bottles", "itch", "gamehub", "minigalaxy", "legendary", "supertuxkart", "0ad",
              "cartridges", "faugus-launcher", "ppsspp", "ppssppqt", "duckstation-qt", "mgba-qt",
              "melonds", "cemu", "xemu", "flycast", "openrct2", "openttd", "minetest", "luanti",
              "veloren", "xonotic", "kpat", "kmines", "ksudoku", "aisleriot", "gnome-mines"},
    "media": {"vlc", "mpv", "haruna", "elisa", "spotify", "smplayer", "celluloid", "stremio", "kodi",
              "rhythmbox", "clementine", "strawberry", "audacious", "totem", "dragon", "kaffeine",
              "freetube", "popcorntime", "plexmediaplayer", "jellyfinmediaplayer", "amarok", "iptvnator",
              "kasts", "gpodder", "shortwave", "tauon", "lollypop", "spotube", "grayjay", "hypnotix",
              "jellyfin-media-player", "plex-desktop", "tubefeeder", "clapper", "showtime"},
    "chat": {"discord", "telegram-desktop", "telegram", "signal-desktop", "element-desktop", "slack",
             "whatsapp-for-linux", "whatsie", "caprine", "neochat", "konversation", "hexchat", "revolt",
             "vesktop", "ayugram-desktop", "kotatogram-desktop", "64gram-desktop", "zapzap", "wasistlos",
             "karere", "fractal", "nheko", "dino", "gajim", "pidgin", "teams-for-linux", "webcord",
             "armcord", "legcord", "skypeforlinux", "viber", "session-desktop"},
    "social": {"tokodon", "tuba", "whalebird", "sengi", "giara", "threddit", "instagram", "facebook",
               "tiktok", "pinterest", "snapchat", "twitter"},
    "news": {"akregator", "liferea", "newsflash", "io.gitlab.news_flash.newsflash", "fluent-reader",
             "rssguard", "quiterss", "gfeeds", "raven-reader", "newsboat", "alligator",
             "tickr", "feedreader"},
}
KNOWN_FLATPAKS = {
    "games": {"com.valvesoftware.Steam", "net.lutris.Lutris", "com.heroicgameslauncher.hgl",
              "org.prismlauncher.PrismLauncher", "com.usebottles.bottles", "org.libretro.RetroArch",
              "page.kramo.Cartridges", "io.github.Faugus.faugus-launcher", "org.ppsspp.PPSSPP",
              "org.DolphinEmu.dolphin-emu", "net.pcsx2.PCSX2", "net.rpcs3.RPCS3", "info.cemu.Cemu",
              "net.minetest.Minetest", "org.luanti.luanti", "io.itch.itch"},
    "media": {"org.videolan.VLC", "io.mpv.Mpv", "com.spotify.Client", "com.stremio.Stremio",
              "tv.kodi.Kodi", "io.freetubeapp.FreeTube", "org.kde.haruna", "org.kde.elisa",
              "org.kde.kasts", "de.haeckerfelix.Shortwave", "com.github.iwalton3.jellyfin-media-player",
              "tv.plex.PlexDesktop", "app.grayjay.Grayjay", "de.schmidhuberj.tubefeeder",
              "com.github.rafostar.Clapper", "io.github.celluloid_player.Celluloid"},
    "chat": {"com.discordapp.Discord", "org.telegram.desktop", "org.signal.Signal", "im.riot.Riot",
             "com.slack.Slack", "dev.vencord.Vesktop", "org.kde.neochat", "org.gnome.Fractal",
             "io.github.NhekoReborn.Nheko", "im.dino.Dino", "org.gajim.Gajim", "com.rtosta.zapzap",
             "io.github.mimbrero.WhatsAppDesktop", "com.github.IsmaelMartinez.teams_for_linux",
             "xyz.armcord.ArmCord", "app.legcord.Legcord", "com.skype.Client", "chat.revolt.RevoltDesktop"},
    "social": {"org.kde.tokodon", "dev.geopjr.Tuba", "social.whalebird.WhalebirdDesktop",
               "io.github.zhrexx.Sengi", "com.mikesamuel.Giara"},
    "news": {"org.kde.akregator", "io.github.lwindolf.Liferea", "io.gitlab.news_flash.NewsFlash",
             "me.hyliu.fluentreader", "io.github.martinrotter.rssguard", "org.gabmus.gfeeds",
             "org.kde.alligator"},
}

# Process names that belong to an app besides its main program, so allowing the app allows them too.
COMPANIONS = {"steam": {"steamwebhelper"}}
# Allowing a game launcher also allows the games it starts from its own folders.
LAUNCHER_MARKERS = {
    "steam": ("/steamapps/", "/compatibilitytools.d/"),
    "com.valvesoftware.Steam": ("/steamapps/", "/compatibilitytools.d/"),
    "lutris": ("/lutris/runners/", "/lutris/runtime/"),
    "net.lutris.Lutris": ("/lutris/runners/", "/lutris/runtime/"),
    "heroic": ("/heroic/tools/",),
    "com.heroicgameslauncher.hgl": ("/heroic/tools/",),
    "bottles": ("/bottles/runners/",),
    "com.usebottles.bottles": ("/bottles/runners/",),
}


def _base(path: str) -> str:
    """File name of a Unix or Windows (Wine) path, lowercased."""
    return path.replace("\\", "/").rsplit("/", 1)[-1].lower()


def _is_interpreter(name: str) -> bool:
    name = name.lower()
    return any(name == i or (name.startswith(i) and name[len(i):].strip("0123456789.-") == "")
               for i in INTERPRETERS)


def parse_desktop_file(path: str) -> dict | None:
    entry, in_main = {}, False
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("["):
                    in_main = line == "[Desktop Entry]"
                    continue
                if in_main and "=" in line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    entry.setdefault(key.strip(), value.strip())
    except OSError:
        return None
    if entry.get("Type", "Application") != "Application" or not entry.get("Exec"):
        return None
    if entry.get("NoDisplay", "").lower() == "true" or entry.get("Hidden", "").lower() == "true":
        return None
    return entry


def parse_exec(exec_line: str) -> tuple[list[str], str | None, str | None]:
    """Return (process names, flatpak app id, snap name) for a desktop Exec line."""
    try:
        tokens = shlex.split(exec_line)
    except ValueError:
        tokens = exec_line.split()
    tokens = [t for t in tokens if not (len(t) == 2 and t[0] == "%")]
    while tokens and (os.path.basename(tokens[0]) == "env" or
                      ("=" in tokens[0] and not tokens[0].startswith("/"))):
        tokens.pop(0)
    if not tokens:
        return [], None, None
    first = tokens[0]
    base = os.path.basename(first)
    if base == "flatpak":
        app_id = None
        for t in tokens[1:]:
            if not t.startswith("-") and t != "run" and "." in t and not t.startswith("@"):
                app_id = t
                break
        return [], app_id, None
    if first.startswith("/snap/bin/"):
        return [base], None, base.split(".")[0]
    if _is_interpreter(base):
        if "-c" in tokens:
            return [], None, None
        for t in tokens[1:]:
            if "://" in t:
                return [], None, None  # "xdg-open https://..." opens a web page, it is not a program
            if not t.startswith("-"):
                script = os.path.basename(t)
                return ([script] if script and not _is_interpreter(script) else []), None, None
        return [], None, None
    return [base], None, None


def classify(entry: dict, names: list[str], flatpak: str | None) -> list[str]:
    cats = {c.strip().lower() for c in entry.get("Categories", "").split(";") if c.strip()}
    lowered = {n.lower() for n in names}
    out = []
    for cat, hints in DESKTOP_CATEGORY_HINTS.items():
        if cats & hints or lowered & KNOWN_NAMES[cat] or (flatpak and flatpak in KNOWN_FLATPAKS[cat]):
            out.append(cat)
    return out


def scan_apps(homes: list[str] | None = None) -> list[dict]:
    """List installed GUI applications with the data needed to recognise their processes."""
    dirs = list(DESKTOP_DIRS)
    if homes is None:
        homes = sorted(glob.glob("/home/*"))
    for home in homes:
        dirs += [os.path.join(home, d) for d in USER_DESKTOP_DIRS]
    apps, seen = [], set()
    for d in dirs:
        for path in sorted(glob.glob(os.path.join(d, "*.desktop"))):
            app_id = os.path.basename(path)[:-len(".desktop")]
            if app_id in seen:
                continue
            entry = parse_desktop_file(path)
            if not entry:
                continue
            names, flatpak, snap = parse_exec(entry["Exec"])
            flatpak = entry.get("X-Flatpak") or flatpak
            snap = entry.get("X-SnapInstanceName") or snap
            names = [n for n in names if n.lower() not in PROTECTED]
            if not (names or flatpak or snap):
                continue
            seen.add(app_id)
            apps.append({
                "id": app_id,
                "name": entry.get("Name", app_id),
                "icon": entry.get("Icon", ""),
                "names": names,
                "flatpak": flatpak,
                "snap": snap,
                "categories": classify(entry, names, flatpak),
            })
    apps.sort(key=lambda a: a["name"].lower())
    return apps


class Proc:
    __slots__ = ("pid", "uid", "exe", "argv", "_cgroup")

    def __init__(self, pid, uid, exe, argv):
        self.pid, self.uid, self.exe, self.argv, self._cgroup = pid, uid, exe, argv, None

    @property
    def cgroup(self) -> str:
        if self._cgroup is None:
            try:
                with open(f"/proc/{self.pid}/cgroup", encoding="utf-8", errors="replace") as fh:
                    self._cgroup = fh.read()
            except OSError:
                self._cgroup = ""
        return self._cgroup

    def age(self) -> float:
        try:
            with open(f"/proc/{self.pid}/stat", "rb") as fh:
                start_ticks = int(fh.read().rsplit(b")", 1)[1].split()[19])
            with open("/proc/uptime") as fh:
                uptime = float(fh.read().split()[0])
            return uptime - start_ticks / os.sysconf("SC_CLK_TCK")
        except (OSError, ValueError, IndexError):
            return 0.0

    def candidate_names(self) -> set[str]:
        names = set()
        exe_base = _base(self.exe) if self.exe else ""
        if exe_base:
            names.add(exe_base)
        if self.argv:
            names.add(_base(self.argv[0]))
            if _is_interpreter(exe_base) or _is_interpreter(_base(self.argv[0])):
                for arg in self.argv[1:4]:
                    if arg in ("-c", "-e", "-lc", "-ic"):
                        break  # inline code follows ("bash -c '...'"), not a script name
                    if not arg.startswith("-"):
                        names.add(_base(arg))
                        break
        names.discard("")
        return names


def iter_procs(min_uid: int = 1000):
    """Yield user processes. System accounts (uid below min_uid) are never touched."""
    me = os.getpid()
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        pid = int(name)
        if pid in (1, me):
            continue
        try:
            uid = os.stat(f"/proc/{pid}").st_uid
            if uid < min_uid:
                continue
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                argv = [a.decode("utf-8", "replace") for a in fh.read().split(b"\0") if a]
            if not argv:
                continue
            try:
                exe = os.readlink(f"/proc/{pid}/exe")
            except OSError:
                exe = ""
            yield Proc(pid, uid, exe, argv)
        except OSError:
            continue


GAME_PATH_MARKERS = [
    ("/steamapps/", "Steam game"),
    ("/compatibilitytools.d/", "Steam (Proton) game"),
    ("/lutris/runners/", "Lutris game"),
    ("/lutris/runtime/", "Lutris game"),
    ("/heroic/tools/", "Heroic game"),
    ("/bottles/runners/", "Bottles game"),
]


class Matcher:
    """Decides whether a process belongs to a blocked application."""

    def __init__(self):
        self.names: dict[str, str] = {}      # lowercase process name -> label
        self.flatpaks: dict[str, str] = {}
        self.snaps: dict[str, str] = {}
        self.game_paths = False
        self.allowed_markers: set[str] = set()  # game folders of launchers the user allowed

    def add(self, label, names=(), flatpak=None, snap=None):
        for n in names:
            n = n.lower()
            if n and n not in PROTECTED and not _is_interpreter(n):
                self.names.setdefault(n, label)
        if flatpak:
            self.flatpaks.setdefault(flatpak, label)
        if snap:
            self.snaps.setdefault(snap, label)

    def empty(self) -> bool:
        return not (self.names or self.flatpaks or self.snaps or self.game_paths)

    def match(self, proc: Proc) -> str | None:
        cands = proc.candidate_names()
        if cands & PROTECTED:
            return None
        for n in cands:
            if n in self.names:
                return self.names[n]
        for snap, label in self.snaps.items():
            if proc.exe.startswith(f"/snap/{snap}/"):
                return label
        if self.game_paths:
            # Games started through Steam, Proton, Lutris, Heroic or Bottles run from these folders,
            # including Windows games whose process is a Wine binary inside the launcher's runner folder.
            for marker, label in GAME_PATH_MARKERS:
                if marker in proc.exe and marker not in self.allowed_markers:
                    return label
        if self.flatpaks:
            cg = proc.cgroup
            for app_id, label in self.flatpaks.items():
                if f"app-flatpak-{app_id}-" in cg:
                    return label
        return None


class _Allowed:
    """Apps the user exempted from their categories ("allowed"). Only category matches are exempted:
    an app the user ticks by itself or types as a process name is still blocked."""

    def __init__(self, entries):
        self.ids, self.names, self.flatpaks, self.snaps = set(), set(), set(), set()
        for app in entries:
            self.ids.add(app.get("id"))
            for n in app.get("names", []):
                n = n.lower()
                self.names.add(n)
                self.names |= COMPANIONS.get(n, set())
            if app.get("flatpak"):
                self.flatpaks.add(app["flatpak"])
            if app.get("snap"):
                self.snaps.add(app["snap"])

    def covers(self, app_id=None, names=(), flatpak=None, snap=None) -> bool:
        return bool((app_id and app_id in self.ids) or {n.lower() for n in names} & self.names
                    or (flatpak and flatpak in self.flatpaks) or (snap and snap in self.snaps))

    def markers(self) -> set[str]:
        out = set()
        for key in self.names | self.flatpaks:
            out.update(LAUNCHER_MARKERS.get(key, ()))
        return out


def build_matcher(apps_cfg: dict, installed: list[dict]) -> Matcher:
    m = Matcher()
    cats = set(apps_cfg.get("categories", []))
    allowed = _Allowed(apps_cfg.get("allowed", []))
    # Explicit choices first, so a label from them wins and they are never exempted.
    for app in apps_cfg.get("selected", []):
        m.add(app["name"], app.get("names", []), app.get("flatpak"), app.get("snap"))
    for n in apps_cfg.get("custom_names", []):
        m.add(n, [n])
    for app in installed:
        if cats & set(app["categories"]) and not allowed.covers(app["id"], app["names"], app["flatpak"], app["snap"]):
            m.add(app["name"], app["names"], app["flatpak"], app["snap"])
    for cat in sorted(cats):
        for n in KNOWN_NAMES.get(cat, ()):
            if not allowed.covers(names=[n]):
                m.add(n, [n])
        for f in KNOWN_FLATPAKS.get(cat, ()):
            if not allowed.covers(flatpak=f):
                m.add(f, flatpak=f)
    m.game_paths = "games" in cats
    m.allowed_markers = allowed.markers()
    return m


# Web browsers, keyed by the name the extension reports in its heartbeat.
def browser_family(proc: Proc) -> str | None:
    exe = proc.exe.lower()
    base = os.path.basename(exe)
    if not exe:
        return None
    if "tor-browser" in exe or base in UNSUPPORTED_BROWSERS:
        return "unsupported"
    if base in ("firefox", "firefox-bin", "firefox-esr", "librewolf", "waterfox", "floorp"):
        return "firefox"
    if base in ("brave", "brave-browser"):
        return "brave"
    if base in ("msedge", "microsoft-edge"):
        return "edge"
    if base == "opera":
        return "opera"
    if base in ("vivaldi", "vivaldi-bin", "helium") or base.startswith("chromium"):
        return "chromium"
    if base == "chrome":
        return "chromium" if "chromium" in exe else "chrome"
    return None


UNSUPPORTED_BROWSERS = {"falkon", "konqueror", "epiphany", "midori", "qutebrowser", "palemoon",
                        "angelfish", "nyxt", "dillo", "min", "netsurf", "netsurf-gtk"}
