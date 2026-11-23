import json
import os
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
_tmp = tempfile.mkdtemp(prefix="focusguard-test-")
os.environ["FOCUSGUARD_ROOT"] = _tmp
os.makedirs(os.path.join(_tmp, "etc"), exist_ok=True)

import importlib  # noqa: E402

from focusguard import apps, config, paths, schedule, system  # noqa: E402


def setUpModule():
    # Point the package at this module's own sandbox, even if another test module ran first.
    os.environ["FOCUSGUARD_ROOT"] = _tmp
    importlib.reload(paths)


def dt(day, hm):
    """day: 0=Monday. 2026-11-16 is a Monday."""
    h, m = map(int, hm.split(":"))
    return datetime(2026, 11, 16 + day, h, m)


class ScheduleTests(unittest.TestCase):
    work = {"days": [0, 1, 2, 3, 4], "start": "09:00", "end": "17:00", "enabled": True}
    night = {"days": [4], "start": "22:00", "end": "02:00", "enabled": True}

    def test_daytime_window(self):
        self.assertEqual(schedule.entry_end(self.work, dt(0, "09:00")), dt(0, "17:00"))
        self.assertEqual(schedule.entry_end(self.work, dt(2, "16:59")), dt(2, "17:00"))
        self.assertIsNone(schedule.entry_end(self.work, dt(0, "08:59")))
        self.assertIsNone(schedule.entry_end(self.work, dt(0, "17:00")))
        self.assertIsNone(schedule.entry_end(self.work, dt(5, "12:00")))

    def test_overnight_window(self):
        self.assertEqual(schedule.entry_end(self.night, dt(4, "23:00")), dt(5, "02:00"))
        self.assertEqual(schedule.entry_end(self.night, dt(5, "01:30")), dt(5, "02:00"))
        self.assertIsNone(schedule.entry_end(self.night, dt(5, "02:00")))
        self.assertIsNone(schedule.entry_end(self.night, dt(4, "01:00")))
        self.assertIsNone(schedule.entry_end(self.night, dt(5, "23:00")))

    def test_disabled_and_empty(self):
        self.assertIsNone(schedule.entry_end(dict(self.work, enabled=False), dt(0, "10:00")))
        self.assertIsNone(schedule.entry_end(dict(self.work, days=[]), dt(0, "10:00")))

    def test_back_to_back_entries_chain(self):
        evening = {"days": [0], "start": "17:00", "end": "20:00", "enabled": True}
        self.assertEqual(schedule.active_until([self.work, evening], dt(0, "10:00")), dt(0, "20:00"))
        self.assertIsNone(schedule.active_until([self.work, evening], dt(0, "20:00")))

    def test_all_day_entry(self):
        allday = {"days": [0], "start": "00:00", "end": "00:00", "enabled": True}
        self.assertEqual(schedule.entry_end(allday, dt(0, "13:00")), dt(1, "00:00"))
        self.assertIsNone(schedule.entry_end(allday, dt(1, "13:00")))

    def test_next_start(self):
        self.assertEqual(schedule.next_start([self.work], dt(0, "08:00")), dt(0, "09:00"))
        self.assertEqual(schedule.next_start([self.work], dt(4, "18:00")), dt(7, "09:00"))
        self.assertIsNone(schedule.next_start([], dt(0, "08:00")))


class ConfigTests(unittest.TestCase):
    def test_categories_leave_whatsapp_alone(self):
        # WhatsApp desktop clients (ZapFast, WhatsApp for Linux) need web.whatsapp.com to connect at all.
        here = os.path.dirname(__file__)
        for path in (os.path.join(here, "..", "focusguard", "data", "web_categories.json"),
                     os.path.join(here, "..", "..", "android", "assets", "web_categories.json")):
            if not os.path.exists(path):
                continue
            with open(path) as fh:
                for cat in json.load(fh).values():
                    self.assertEqual([d for d in cat["domains"] if "whatsapp" in d], [], path)

    def test_normalize_domain(self):
        n = config.normalize_domain
        self.assertEqual(n("https://www.Example.com/path?q=1"), "example.com")
        self.assertEqual(n("  sub.example.co.uk  "), "sub.example.co.uk")
        self.assertEqual(n("user@example.com:8080/x"), "example.com")
        self.assertIsNone(n("not a domain"))
        self.assertIsNone(n("localhost"))
        self.assertIsNone(n("0.0.0.0 evil.com\n127.0.0.1 x"))

    def test_sanitize_drops_bad_values_and_secrets(self):
        cfg = config.sanitize({
            "password": {"salt": "00", "hash": "00"}, "session": {"until": 1},
            "apps": {"categories": ["games", "bogus"], "custom_names": ["ok", "../bad/path"],
                     "selected": [{"id": "a", "names": ["x"], "flatpak": None}, "junk"]},
            "web": {"categories": ["social"], "custom_blocked": ["http://a.com/x", "###"], "exceptions": 5},
            "youtube": {"mode": "weird", "allowed_categories": ["Gaming", "Nope"], "unknown": "allow"},
            "schedules": [{"days": [0, 9, "x", True], "start": "09:00", "end": "25:00"},
                          {"days": [6, 0], "start": "09:00", "end": "10:00"}],
            "protection": {"strict": "yes", "require_extension": True},
        })
        self.assertIsNone(cfg["password"])
        self.assertIsNone(cfg["session"])
        self.assertEqual(cfg["apps"]["categories"], ["games"])
        self.assertEqual(cfg["apps"]["custom_names"], ["ok"])
        self.assertEqual(len(cfg["apps"]["selected"]), 1)
        self.assertEqual(cfg["web"]["custom_blocked"], ["a.com"])
        self.assertEqual(cfg["web"]["exceptions"], [])
        self.assertEqual(cfg["youtube"]["mode"], "filter")
        self.assertEqual(cfg["youtube"]["allowed_categories"], ["Gaming"])
        self.assertEqual(cfg["youtube"]["unknown"], "allow")
        self.assertEqual(cfg["schedules"], [{"name": "", "days": [0, 6], "start": "09:00", "end": "10:00", "enabled": True}])
        self.assertFalse(cfg["protection"]["strict"])
        self.assertTrue(cfg["protection"]["require_extension"])

    def test_password_roundtrip(self):
        stored = config.hash_password("s3cret")
        self.assertTrue(config.verify_password(stored, "s3cret"))
        self.assertFalse(config.verify_password(stored, "wrong"))
        self.assertFalse(config.verify_password(stored, None))
        self.assertTrue(config.verify_password(None, None))

    def test_save_load_keeps_password_and_is_private(self):
        cfg = config.sanitize({})
        cfg["password"] = config.hash_password("pw")
        cfg["session"] = {"until": 123.0}
        config.save(cfg)
        self.assertEqual(os.stat(paths.CONFIG_FILE).st_mode & 0o777, 0o600)
        loaded = config.load()
        self.assertEqual(loaded["password"], cfg["password"])
        self.assertEqual(loaded["session"], {"until": 123.0})
        self.assertNotIn("password", config.public_view(loaded))


class AppTests(unittest.TestCase):
    def test_parse_exec(self):
        self.assertEqual(apps.parse_exec("/usr/games/steam %U"), (["steam"], None, None))
        self.assertEqual(apps.parse_exec("env FOO=1 vlc --started-from-file %U"), (["vlc"], None, None))
        self.assertEqual(apps.parse_exec("/usr/bin/flatpak run --branch=stable --arch=x86_64 "
                                         "--command=discord com.discordapp.Discord @@u %U @@"),
                         ([], "com.discordapp.Discord", None))
        self.assertEqual(apps.parse_exec("/snap/bin/spotify %U"), (["spotify"], None, "spotify"))
        self.assertEqual(apps.parse_exec("python3 /opt/game/run_game.py"), (["run_game.py"], None, None))
        self.assertEqual(apps.parse_exec("sh -c 'something'")[0], [])
        self.assertEqual(apps.parse_exec("xdg-open https://kfocus.org/support/wf")[0], [])

    def test_scan_and_classify(self):
        home = tempfile.mkdtemp()
        d = os.path.join(home, ".local/share/applications")
        os.makedirs(d)
        with open(os.path.join(d, "supergame.desktop"), "w") as fh:
            fh.write("[Desktop Entry]\nType=Application\nName=Super Game\nExec=supergame %f\nCategories=Game;ArcadeGame;\n"
                     "[Desktop Action x]\nExec=other\n")
        with open(os.path.join(d, "hidden.desktop"), "w") as fh:
            fh.write("[Desktop Entry]\nType=Application\nName=Hidden\nExec=hidden\nNoDisplay=true\n")
        with open(os.path.join(d, "editor.desktop"), "w") as fh:
            fh.write("[Desktop Entry]\nType=Application\nName=Editor\nExec=kate %U\nCategories=Utility;TextEditor;\n")
        found = {a["id"]: a for a in apps.scan_apps([home])}
        self.assertEqual(found["supergame"]["categories"], ["games"])
        self.assertEqual(found["supergame"]["names"], ["supergame"])
        self.assertEqual(found["editor"]["categories"], [])
        self.assertNotIn("hidden", found)

    def test_matcher(self):
        m = apps.build_matcher({"categories": ["games"], "selected": [
            {"id": "x", "name": "Disc", "names": ["Discord"], "flatpak": None, "snap": "spot"}],
            "custom_names": ["mygame.exe", "plasmashell", "python3"]}, [])
        self.assertEqual(m.match(apps.Proc(1, 1000, "/usr/share/discord/Discord", ["/usr/share/discord/Discord"])), "Disc")
        self.assertEqual(m.match(apps.Proc(1, 1000, "/usr/bin/wine64", ["wine64", "MyGame.exe"])), "mygame.exe")
        self.assertEqual(m.match(apps.Proc(1, 1000, "/snap/spot/12/bin/x", ["x"])), "Disc")
        self.assertEqual(m.match(apps.Proc(1, 1000, "/home/u/.steam/steamapps/common/Game/game.bin", ["game.bin"])), "Steam game")
        self.assertIsNotNone(m.match(apps.Proc(1, 1000, "/home/u/.steam/ubuntu12_32/steam", ["steam"])))
        self.assertIsNone(m.match(apps.Proc(1, 1000, "/usr/bin/plasmashell", ["plasmashell"])))
        self.assertIsNone(m.match(apps.Proc(1, 1000, "/usr/bin/python3.12", ["python3", "study.py"])))
        self.assertIsNone(m.match(apps.Proc(1, 1000, "/usr/bin/kate", ["kate"])))
        # A shell running inline code that merely mentions a blocked name is left alone.
        self.assertIsNone(m.match(apps.Proc(1, 1000, "/usr/bin/bash", ["bash", "-c", "ls ~/projects/discord"])))
        # Windows games under Lutris or Proton run as Wine binaries from the launcher's folders.
        wine = "/home/u/.local/share/lutris/runners/wine/wine-ge-8-26/bin/wine64-preloader"
        self.assertEqual(m.match(apps.Proc(1, 1000, wine, ["C:\\Games\\MW3\\iw5sp.exe"])), "Lutris game")
        proton = "/home/u/.steam/root/compatibilitytools.d/GE-Proton9/files/bin/wine64-preloader"
        self.assertEqual(m.match(apps.Proc(1, 1000, proton, ["Z:\\game.exe"])), "Steam (Proton) game")
        none = apps.build_matcher({"categories": ["chat"], "selected": [], "custom_names": []}, [])
        self.assertIsNone(none.match(apps.Proc(1, 1000, wine, ["C:\\Games\\MW3\\iw5sp.exe"])))
        self.assertEqual(apps.build_matcher({"categories": [], "selected": [], "custom_names": ["iw5sp.exe"]}, [])
                         .match(apps.Proc(1, 1000, wine, ["C:\\Games\\MW3\\iw5sp.exe"])), "iw5sp.exe")

    def test_category_exceptions(self):
        P = lambda exe, *argv: apps.Proc(1, 1000, exe, list(argv) or [exe])
        installed = [
            {"id": "discord", "name": "Discord", "names": ["Discord"], "flatpak": None, "snap": None, "categories": ["chat"]},
            {"id": "org.telegram.desktop", "name": "Telegram", "names": [], "flatpak": "org.telegram.desktop",
             "snap": None, "categories": ["chat"]},
            {"id": "slack", "name": "Slack", "names": ["slack"], "flatpak": None, "snap": "slack", "categories": ["chat"]},
            {"id": "steam", "name": "Steam", "names": ["steam"], "flatpak": None, "snap": None, "categories": ["games"]},
            {"id": "lutris", "name": "Lutris", "names": ["lutris"], "flatpak": None, "snap": None, "categories": ["games"]},
        ]
        pick = lambda *ids: [{k: a[k] for k in ("id", "name", "names", "flatpak", "snap")} for a in installed if a["id"] in ids]
        m = apps.build_matcher({"categories": ["chat", "games"], "selected": [], "custom_names": [],
                                "allowed": pick("discord", "org.telegram.desktop", "steam")}, installed)
        # Allowed apps survive their category, including names the built-in lists know.
        self.assertIsNone(m.match(P("/usr/share/discord/Discord")))
        self.assertIsNone(m.match(P("/usr/bin/steam")))
        self.assertIsNone(m.match(P("/home/u/.steam/ubuntu12_64/steamwebhelper")))
        self.assertIsNone(m.match(P("/home/u/.steam/steamapps/common/Game/game.bin")))
        self.assertNotIn("org.telegram.desktop", m.flatpaks)
        # The rest of the category is still blocked.
        self.assertEqual(m.match(P("/snap/slack/1/usr/lib/slack/slack")), "Slack")
        self.assertIsNotNone(m.match(P("/usr/bin/signal-desktop")))
        self.assertEqual(m.match(P("/usr/bin/lutris")), "Lutris")
        wine = "/home/u/.local/share/lutris/runners/wine/ge/bin/wine64-preloader"
        self.assertEqual(m.match(P(wine, "C:\\g.exe")), "Lutris game")
        # A ticked app or typed process name is blocked even if it is also listed as allowed.
        m2 = apps.build_matcher({"categories": ["chat"], "selected": pick("discord"), "custom_names": ["telegram-desktop"],
                                 "allowed": pick("discord", "org.telegram.desktop")}, installed)
        self.assertEqual(m2.match(P("/usr/share/discord/Discord")), "Discord")
        self.assertEqual(m2.match(P("/usr/bin/telegram-desktop")), "telegram-desktop")
        # Without the category, an exception blocks nothing and allows nothing extra.
        m3 = apps.build_matcher({"categories": [], "selected": [], "custom_names": [], "allowed": pick("steam")}, installed)
        self.assertTrue(m3.empty())

    def test_new_categories(self):
        d = tempfile.mkdtemp()
        home = os.path.join(d, "home")
        apps_dir = os.path.join(home, ".local/share/applications")
        os.makedirs(apps_dir)
        files = {"akregator": "Exec=akregator %u\nCategories=Qt;KDE;Network;News;\n",
                 "tokodon": "Exec=tokodon\nCategories=Qt;KDE;Network;\n",
                 "rss": "Exec=myreader\nCategories=Network;Feed;\n"}
        for name, body in files.items():
            with open(os.path.join(apps_dir, name + ".desktop"), "w") as fh:
                fh.write("[Desktop Entry]\nType=Application\nName=" + name + "\n" + body)
        found = {a["id"]: a["categories"] for a in apps.scan_apps([home]) if a["id"] in files}
        self.assertEqual(found, {"akregator": ["news"], "tokodon": ["social"], "rss": ["news"]})
        for cat in ("social", "news"):
            self.assertIn(cat, config.APP_CATEGORIES)
            self.assertFalse(apps.build_matcher({"categories": [cat], "selected": [], "custom_names": []}, []).empty())

    def test_sanitize_allowed(self):
        cfg = config.sanitize({"apps": {"categories": ["chat", "social", "news"],
                                        "selected": [{"id": "a", "names": ["a"]}],
                                        "allowed": [{"id": "a", "names": ["a"]}, {"id": "b", "names": ["b/x", "b"]}, 7]}})
        self.assertEqual(cfg["apps"]["categories"], ["chat", "social", "news"])
        self.assertEqual([(x["id"], x["names"]) for x in cfg["apps"]["allowed"]], [("b", ["b"])])
        self.assertEqual(config.sanitize({})["apps"]["allowed"], [])

    def test_arabic_translation(self):
        import ast
        import re
        from focusguard import i18n
        from focusguard.lang_ar import AR
        src = open(os.path.join(os.path.dirname(__file__), "..", "focusguard", "gui.py"), encoding="utf-8").read()
        used = {n.args[0].value for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "_" and n.args
                and isinstance(n.args[0], ast.Constant)}
        used |= set(config.APP_CATEGORIES.values()) | {v.split(" ")[0] for v in config.APP_CATEGORIES.values()}
        used |= set(config.YOUTUBE_CATEGORIES)
        with open(os.path.join(os.path.dirname(__file__), "..", "focusguard", "data", "web_categories.json")) as fh:
            used |= {v["label"] for v in json.load(fh).values()}
        self.assertEqual(sorted(used - set(AR)), [])
        for en, ar in AR.items():
            self.assertEqual(sorted(re.findall(r"\{[^}]*\}", en)), sorted(re.findall(r"\{[^}]*\}", ar)), en)
        try:
            i18n.set_language("ar")
            self.assertEqual(i18n._("Apply changes"), "تطبيق التغييرات")
            self.assertEqual(i18n.tr_message("Closed Steam: it is blocked right now."), "أُغلق Steam: إنه محظور الآن.")
            self.assertEqual(i18n.tr_message("Something new."), "Something new.")
            i18n.set_language("fr")
            self.assertEqual(i18n.language(), "en")
            self.assertEqual(i18n._("Apply changes"), "Apply changes")
        finally:
            i18n.set_language("en")

    def test_language_preference(self):
        from focusguard import i18n
        old = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
        try:
            self.assertEqual(i18n.load_language(), "en")
            i18n.save_language("ar")
            self.assertEqual(i18n.load_language(), "ar")
            with open(i18n.pref_file(), "w") as fh:
                fh.write("[broken")
            self.assertEqual(i18n.load_language(), "en")
        finally:
            if old is None:
                del os.environ["XDG_CONFIG_HOME"]
            else:
                os.environ["XDG_CONFIG_HOME"] = old

    def test_browser_family(self):
        f = lambda exe: apps.browser_family(apps.Proc(1, 1000, exe, [exe]))
        self.assertEqual(f("/snap/firefox/4793/usr/lib/firefox/firefox"), "firefox")
        self.assertEqual(f("/opt/google/chrome/chrome"), "chrome")
        self.assertEqual(f("/snap/chromium/2900/usr/lib/chromium-browser/chrome"), "chromium")
        self.assertEqual(f("/opt/brave.com/brave/brave"), "brave")
        self.assertEqual(f("/home/u/tor-browser/Browser/firefox"), "unsupported")
        self.assertEqual(f("/usr/bin/falkon"), "unsupported")
        self.assertEqual(f("/opt/helium/helium"), "chromium")
        self.assertIsNone(f("/usr/bin/kate"))


class LinkTests(unittest.TestCase):
    def test_code_helpers(self):
        from focusguard import link
        code = link.new_code()
        self.assertEqual(link.normalize_code(link.format_code(code).lower()), code)
        self.assertIsNone(link.normalize_code("too-short"))
        self.assertRegex(link.topic(code), r"^fg[0-9a-f]{40}$")
        self.assertNotEqual(link.topic(code), link.topic(link.new_code()))

    def test_link_survives_save_but_not_set_config(self):
        cfg = config.sanitize({"link": {"code": "A" * 16, "server": "https://evil.example"}})
        self.assertIsNone(cfg["link"])  # clients cannot set it
        cfg["link"] = {"code": "B" * 16, "server": "https://ntfy.sh"}
        config.save(cfg)
        self.assertEqual(config.load()["link"], cfg["link"])
        self.assertEqual(config.public_view(cfg)["link"]["code"], "B" * 16)

    def test_state_has_no_secrets(self):
        from focusguard import link
        cfg = config.sanitize({"apps": {"selected": [{"id": "x", "names": ["secretapp"]}]}})
        cfg["password"] = config.hash_password("pw")
        cfg["link"] = {"code": "B" * 16, "server": "s"}
        text = json.dumps(link.build_state(cfg))
        for needle in ("hash", "salt", "secretapp", "B" * 16):
            self.assertNotIn(needle, text)


class HostsTests(unittest.TestCase):
    def test_apply_and_remove(self):
        original = "127.0.0.1 localhost\n# my own entry\n10.0.0.5 nas\n"
        with open(paths.HOSTS_FILE, "w") as fh:
            fh.write(original)
        self.assertTrue(system.apply_hosts(["reddit.com", "www.x.com"]))
        text = open(paths.HOSTS_FILE).read()
        self.assertIn("0.0.0.0 reddit.com\n", text)
        self.assertIn("0.0.0.0 www.reddit.com\n", text)
        self.assertIn(":: www.x.com\n", text)
        self.assertNotIn("www.www.", text)
        self.assertIn("10.0.0.5 nas", text)
        self.assertFalse(system.apply_hosts(["www.x.com", "reddit.com"]))  # already in place
        self.assertTrue(system.apply_hosts(["reddit.com"]))
        self.assertNotIn("x.com", open(paths.HOSTS_FILE).read())
        self.assertTrue(system.apply_hosts([]))
        self.assertEqual(open(paths.HOSTS_FILE).read(), original)

    def test_firefox_policy_merge_keeps_foreign_keys(self):
        os.makedirs(os.path.dirname(paths.FIREFOX_POLICY), exist_ok=True)
        with open(paths.FIREFOX_POLICY, "w") as fh:
            json.dump({"policies": {"DisableTelemetry": True}}, fh)
        system.apply_browser_policies(True)
        doc = json.load(open(paths.FIREFOX_POLICY))
        self.assertTrue(doc["policies"]["DisablePrivateBrowsing"])
        self.assertTrue(doc["policies"]["DisableTelemetry"])
        chrome = os.path.join(paths.CHROMIUM_POLICY_DIRS[0], "focusguard.json")
        self.assertEqual(json.load(open(chrome))["IncognitoModeAvailability"], 1)
        system.apply_browser_policies(False)
        self.assertEqual(json.load(open(paths.FIREFOX_POLICY)), {"policies": {"DisableTelemetry": True}})
        self.assertFalse(os.path.exists(chrome))


if __name__ == "__main__":
    unittest.main()
