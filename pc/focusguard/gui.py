"""FocusGuard settings app and tray icon (PyQt6, at home on KDE Plasma)."""
from __future__ import annotations

import os
import sys
from datetime import datetime

from PyQt6.QtCore import QLibraryInfo, QLocale, QSize, Qt, QTime, QTimer, QTranslator
from PyQt6.QtGui import QAction, QIcon, QKeySequence, QShortcut
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QGroupBox,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget, QMainWindow, QMenu,
    QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QStackedWidget, QSystemTrayIcon, QTableWidget,
    QTimeEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import apps, client, config, i18n, link
from .i18n import _, tr_message

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
EXTENSION_DIR = "/opt/focusguard/extension"


FULL_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def fmt_time(ts) -> str:
    """Clock time in English with Western digits, whatever the system language is."""
    if not ts:
        return ""
    d = datetime.fromtimestamp(ts)
    clock = f"{d.hour:02d}:{d.minute:02d}"
    return clock if d.date() == datetime.now().date() else f"{_(FULL_DAYS[d.weekday()])} {clock}"


def fmt_left(ts) -> str:
    minutes = max(0, int((ts - datetime.now().timestamp() + 59) // 60))
    hours, minutes = divmod(minutes, 60)
    return (_("{h} h {m:02d} min left").format(h=hours, m=minutes) if hours
            else _("{m} min left").format(m=minutes))


# Only named widgets are styled, and only with palette colours, so the window keeps the
# desktop's own theme (Breeze, light or dark) and costs nothing extra to draw.
STYLE = """
QFrame#hero, QFrame#tile { background: palette(base); border: 1px solid palette(midlight); border-radius: 10px; }
QLabel#banner { font-size: 16pt; font-weight: 600; }
QLabel#pageTitle { font-size: 13pt; font-weight: 600; }
QLabel#tileCaption { color: palette(placeholder-text); font-size: 9pt; }
QLabel#tileValue { font-size: 11pt; font-weight: 600; }
QLabel#pill { border-radius: 8px; padding: 4px 12px; font-weight: 700; font-size: 9pt; }
QLabel#pill[state="on"] { background: #1f9d55; color: white; }
QLabel#pill[state="off"] { background: palette(mid); color: palette(window-text); }
QLabel#pill[state="down"] { background: #c0392b; color: white; }
QListWidget#nav { border: none; background: transparent; outline: 0; }
QListWidget#nav::item { padding: 9px 10px; margin: 1px 0; border-radius: 7px; }
QListWidget#nav::item:hover { background: palette(midlight); }
QListWidget#nav::item:selected { background: palette(highlight); color: palette(highlighted-text); }
"""


class Pages(QWidget):
    """A sidebar of sections with the chosen section beside it."""

    def __init__(self):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(14)
        self.nav = QListWidget(objectName="nav")
        self.nav.setFixedWidth(170)
        self.nav.setIconSize(QSize(22, 22))
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.stack = QStackedWidget()
        row.addWidget(self.nav)
        row.addWidget(self.stack, 1)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)

    def addTab(self, page: QWidget, icon: QIcon, title: str, subtitle: str = ""):
        holder = QWidget()
        v = QVBoxLayout(holder)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        v.addWidget(QLabel(title, objectName="pageTitle"))
        if subtitle:
            v.addWidget(note(subtitle))
        page.layout().setContentsMargins(0, 8, 0, 0)
        page.layout().setSpacing(10)
        v.addWidget(page, 1)
        self.stack.addWidget(holder)
        self.nav.addItem(title)
        self.nav.item(self.nav.count() - 1).setIcon(icon)
        if self.nav.count() == 1:
            self.nav.setCurrentRow(0)

    def count(self) -> int:
        return self.stack.count()

    def setCurrentIndex(self, index: int):
        self.nav.setCurrentRow(index)


def note(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet("color: palette(placeholder-text);")
    return label


def lines(edit: QPlainTextEdit) -> list[str]:
    return [ln.strip() for ln in edit.toPlainText().splitlines() if ln.strip()]


class PasswordDialog(QDialog):
    def __init__(self, parent, has_password: bool):
        super().__init__(parent)
        self.setWindowTitle(_("FocusGuard password"))
        form = QFormLayout(self)
        self.old = QLineEdit(echoMode=QLineEdit.EchoMode.Password)
        self.new = QLineEdit(echoMode=QLineEdit.EchoMode.Password)
        self.again = QLineEdit(echoMode=QLineEdit.EchoMode.Password)
        if has_password:
            form.addRow(_("Current password"), self.old)
        form.addRow(_("New password"), self.new)
        form.addRow(_("Repeat new password"), self.again)
        form.addRow(note(_("Leave the new password empty to remove it. There is no recovery if you forget it, "
                         "short of removing FocusGuard as the system administrator.")))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._check)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _check(self):
        if self.new.text() != self.again.text():
            QMessageBox.warning(self, _("FocusGuard"), _("The two new passwords do not match."))
            return
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(_("FocusGuard"))
        self.setWindowIcon(QIcon.fromTheme("security-high"))
        self.resize(940, 680)
        self.setStyleSheet(STYLE)
        self.cfg = None
        self.status = {}
        self.web_categories = {}
        self.installed = apps.scan_apps([os.path.expanduser("~")])
        self.seen_event = None
        self.drawn_event = -1
        self.tray = None

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(16, 16, 16, 12)
        outer.setSpacing(14)

        hero = QFrame(objectName="hero")
        hl = QHBoxLayout(hero)
        hl.setContentsMargins(18, 14, 18, 14)
        hl.setSpacing(16)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.banner = QLabel(objectName="banner")
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet("color: palette(placeholder-text);")
        text.addWidget(self.banner)
        text.addWidget(self.detail)
        hl.addLayout(text, 1)
        self.pill = QLabel(objectName="pill")
        hl.addWidget(self.pill, 0, Qt.AlignmentFlag.AlignVCenter)
        outer.addWidget(hero)

        self.tabs = Pages()
        outer.addWidget(self.tabs, 1)

        self._build_status_tab()
        self._build_apps_tab()
        self._build_web_tab()
        self._build_youtube_tab()
        self._build_schedule_tab()
        self._build_protection_tab()
        self._build_phone_tab()

        bottom = QHBoxLayout()
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.quit_btn = QPushButton(QIcon.fromTheme("application-exit"), _("Quit"))
        self.quit_btn.setToolTip(_("Close this window and the tray icon. Blocking keeps running in the background."))
        bottom.addWidget(self.quit_btn)
        self.lang_box = QComboBox()
        for code, name in i18n.LANGUAGES.items():
            self.lang_box.addItem(name, code)
        self.lang_box.setCurrentIndex(max(0, self.lang_box.findData(i18n.language())))
        self.lang_box.setToolTip(_("Language"))
        self.lang_box.currentIndexChanged.connect(self._language_picked)
        self.on_language = None  # set by main(): rebuilds the window in the new language
        bottom.addWidget(QLabel(_("Language:")))
        bottom.addWidget(self.lang_box)
        bottom.addWidget(self.message, 1)
        self.revert_btn = QPushButton(_("Discard changes"))
        self.revert_btn.clicked.connect(self.load_config)
        self.apply_btn = QPushButton(QIcon.fromTheme("dialog-ok-apply"), _("Apply changes"))
        self.apply_btn.clicked.connect(self.apply)
        self.apply_btn.setDefault(True)
        self.apply_btn.setMinimumWidth(140)
        bottom.addWidget(self.revert_btn)
        bottom.addWidget(self.apply_btn)
        outer.addLayout(bottom)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_status)
        self.timer.start(3000)
        self.load_config()
        self.refresh_status()

    # ---- tabs -------------------------------------------------------------------
    def _build_status_tab(self):
        tab = QWidget()
        v = QVBoxLayout(tab)
        tiles = QHBoxLayout()
        tiles.setSpacing(10)
        self.tiles = {}
        for key, caption in (("when", _("Ends")), ("schedule", _("Schedule")), ("extension", _("Browser extension")),
                             ("lock", _("Protection"))):
            frame = QFrame(objectName="tile")
            fl = QVBoxLayout(frame)
            fl.setContentsMargins(14, 10, 14, 10)
            fl.setSpacing(2)
            cap = QLabel(caption, objectName="tileCaption")
            val = QLabel("–", objectName="tileValue")
            fl.addWidget(cap)
            fl.addWidget(val)
            tiles.addWidget(frame, 1)
            self.tiles[key] = (cap, val)
        v.addLayout(tiles)

        box = QGroupBox(_("Focus session"))
        h = QHBoxLayout(box)
        h.addWidget(QLabel(_("Block everything on my lists for")))
        self.session_minutes = QSpinBox(minimum=5, maximum=1440, value=50, singleStep=5, suffix=_(" minutes"))
        h.addWidget(self.session_minutes)
        start = QPushButton(QIcon.fromTheme("media-playback-start"), _("Start now"))
        start.clicked.connect(lambda: self.start_session(self.session_minutes.value()))
        h.addWidget(start)
        self.stop_btn = QPushButton(_("End session early"))
        self.stop_btn.clicked.connect(self.stop_session)
        h.addStretch(1)
        for minutes in (25, 50, 90):
            quick = QPushButton(_("{m} min").format(m=minutes))
            quick.setToolTip(_("Start a {m} minute session now").format(m=minutes))
            quick.clicked.connect(lambda _=False, m=minutes: self.start_session(m))
            h.addWidget(quick)
        h.addWidget(self.stop_btn)
        v.addWidget(box)

        v.addWidget(QLabel(_("Recent activity")))
        self.events = QListWidget()
        self.events.setAlternatingRowColors(True)
        v.addWidget(self.events, 1)
        self.tabs.addTab(tab, QIcon.fromTheme("view-calendar-day"), _("Status"))

    def _build_apps_tab(self):
        tab = QWidget()
        v = QVBoxLayout(tab)
        box = QGroupBox(_("Block by category"))
        bv = QVBoxLayout(box)
        self.app_cat_boxes = {}
        for key, label in config.APP_CATEGORIES.items():
            count = sum(1 for a in self.installed if key in a["categories"])
            cb = QCheckBox(_("{label}  ({n} installed)").format(label=_(label), n=count))
            cb.stateChanged.connect(self._mark_category_apps)
            self.app_cat_boxes[key] = cb
            bv.addWidget(cb)
        bv.addWidget(note(_("Categories also cover apps you install later. The Games category also closes Steam, Lutris and Proton games.")))
        v.addWidget(box)

        v.addWidget(QLabel(_("Applications")))
        v.addWidget(note(_("Tick an app to block it on its own. Apps in a ticked category are ticked for you: "
                         "untick one to keep it allowed (allowing Steam, Lutris, Heroic or Bottles also allows their games).")))
        self.app_search = QLineEdit(placeholderText=_("Search installed applications…"), clearButtonEnabled=True)
        self.app_search.textChanged.connect(self._filter_apps)
        v.addWidget(self.app_search)
        self.app_tree = QTreeWidget()
        self.app_tree.setHeaderLabels([_("Application"), _("Category"), _("Recognised as")])
        self.app_tree.setRootIsDecorated(False)
        self.app_tree.setAlternatingRowColors(True)
        self.app_tree.setUniformRowHeights(True)
        self.app_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for app in self.installed:
            cats = ", ".join(_(config.APP_CATEGORIES[c].split(" ")[0]) for c in app["categories"])
            ident = app["flatpak"] or (f"snap {app['snap']}" if app["snap"] and not app["names"] else ", ".join(app["names"]))
            item = QTreeWidgetItem([app["name"], cats, ident])
            item.setIcon(0, QIcon.fromTheme(app["icon"]) if app["icon"] and not app["icon"].startswith("/") else QIcon(app["icon"]))
            item.setCheckState(0, Qt.CheckState.Unchecked)
            item.setData(0, Qt.ItemDataRole.UserRole, app)
            self.app_tree.addTopLevelItem(item)
        self.app_selected, self.app_allowed, self._app_sync = set(), set(), False
        self.app_tree.itemChanged.connect(self._app_ticked)
        v.addWidget(self.app_tree, 1)

        v.addWidget(QLabel(_("Other programs to block, by process name (one per line)")))
        self.custom_names = QPlainTextEdit()
        self.custom_names.setMaximumHeight(70)
        self.custom_names.setPlaceholderText(_("e.g. a game started from a folder or through Wine: mygame.exe"))
        v.addWidget(self.custom_names)
        self.tabs.addTab(tab, QIcon.fromTheme("applications-games"), _("Applications"),
                         _("Programs that are closed while a block is running."))

    def _build_web_tab(self):
        tab = QWidget()
        v = QVBoxLayout(tab)
        self.web_box = QGroupBox(_("Block website categories"))
        self.web_box_layout = QVBoxLayout(self.web_box)
        self.web_cat_boxes = {}
        v.addWidget(self.web_box)
        h = QHBoxLayout()
        left, right = QVBoxLayout(), QVBoxLayout()
        left.addWidget(QLabel(_("Also block these sites (one per line)")))
        self.custom_blocked = QPlainTextEdit()
        self.custom_blocked.setPlaceholderText("example.com")
        left.addWidget(self.custom_blocked)
        right.addWidget(QLabel(_("Never block these sites (one per line)")))
        self.exceptions = QPlainTextEdit()
        self.exceptions.setPlaceholderText(_("A site from a category that you need for work"))
        right.addWidget(self.exceptions)
        h.addLayout(left)
        h.addLayout(right)
        v.addLayout(h, 1)
        v.addWidget(note(_("Sites are blocked for the whole computer through the hosts file, and more precisely "
                         "(including every subdomain) by the browser extension. YouTube has its own tab.")))
        self.tabs.addTab(tab, QIcon.fromTheme("applications-internet"), _("Websites"),
                         _("Sites that cannot be opened while a block is running."))

    def _build_youtube_tab(self):
        tab = QWidget()
        v = QVBoxLayout(tab)
        form = QFormLayout()
        self.yt_mode = QComboBox()
        self.yt_mode.addItem(_("Filtered: only the kinds of video I tick below can play"), "filter")
        self.yt_mode.addItem(_("Blocked completely"), "block")
        self.yt_mode.addItem(_("Not restricted"), "allow")
        form.addRow(_("During a block, YouTube is"), self.yt_mode)
        v.addLayout(form)

        self.yt_filter_panel = QWidget()
        pv = QVBoxLayout(self.yt_filter_panel)
        pv.setContentsMargins(0, 0, 0, 0)
        h = QHBoxLayout()
        box = QGroupBox(_("Ticked kinds of video play, unticked kinds are blocked"))
        bv = QVBoxLayout(box)
        bv.setSpacing(3)
        self.yt_cat_boxes = {}
        study = config.YOUTUBE_CATEGORIES[:5]
        bv.addWidget(QLabel(_("<b>Usually useful for study</b>")))
        for cat in config.YOUTUBE_CATEGORIES:
            if cat == config.YOUTUBE_CATEGORIES[len(study)]:
                bv.addWidget(QLabel(_("<b>Usually entertainment</b> (leave unticked to block)")))
            cb = QCheckBox(_(cat).replace("&", "&&"))
            self.yt_cat_boxes[cat] = cb
            bv.addWidget(cb)
        bv.addStretch(1)
        h.addWidget(box)
        right = QVBoxLayout()
        right.addWidget(QLabel(_("Exceptions: always allow videos mentioning (one per line)")))
        self.yt_allow = QPlainTextEdit()
        self.yt_allow.setPlaceholderText(_("Your subjects, courses or channels, e.g.\npharmacology\nkhan academy"))
        right.addWidget(self.yt_allow)
        right.addWidget(QLabel(_("Exceptions: always block videos mentioning (one per line)")))
        self.yt_block = QPlainTextEdit()
        self.yt_block.setPlaceholderText(_("e.g.\ngameplay\nlet's play\nreaction"))
        right.addWidget(self.yt_block)
        h.addLayout(right, 1)
        pv.addLayout(h, 1)

        self.yt_unknown = QCheckBox(_("Block a video when its kind cannot be determined"))
        self.yt_shorts = QCheckBox(_("Block YouTube Shorts"))
        pv.addWidget(self.yt_unknown)
        pv.addWidget(self.yt_shorts)
        pv.addWidget(note(_("The kind of each video is the category its uploader chose on YouTube. The words you list "
                          "are looked for in the title, channel name and tags, and override the kind: for example, "
                          "add your subjects so a lecture filed under Entertainment still plays. "
                          "Filtering needs the browser extension.")))
        v.addWidget(self.yt_filter_panel, 1)
        self.yt_off_note = note("")
        v.addWidget(self.yt_off_note)
        v.addStretch(0)
        self.yt_mode.currentIndexChanged.connect(self._yt_mode_changed)
        self.tabs.addTab(tab, QIcon.fromTheme("media-playback-start"), _("YouTube"),
                         _("Keep YouTube for study and block the rest."))

    def _build_schedule_tab(self):
        tab = QWidget()
        v = QVBoxLayout(tab)
        self.sched = QTableWidget(0, 11)
        self.sched.setHorizontalHeaderLabels([_("On"), _("Name")] + [_(d) for d in DAYS] + [_("From"), _("Until")])
        self.sched.verticalHeader().setVisible(False)
        self.sched.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.sched.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.sched.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.sched.setAlternatingRowColors(True)
        self.sched.setShowGrid(False)
        self.sched.verticalHeader().setDefaultSectionSize(38)
        v.addWidget(self.sched, 1)
        h = QHBoxLayout()
        add = QPushButton(QIcon.fromTheme("list-add"), _("Add time block"))
        add.clicked.connect(lambda: self._add_schedule_row(
            {"name": _("Study time"), "days": [0, 1, 2, 3, 4], "start": "09:00", "end": "17:00", "enabled": True}))
        remove = QPushButton(QIcon.fromTheme("list-remove"), _("Remove selected"))
        remove.clicked.connect(lambda: self.sched.removeRow(self.sched.currentRow()) if self.sched.currentRow() >= 0 else None)
        h.addWidget(add)
        h.addWidget(remove)
        h.addStretch(1)
        v.addLayout(h)
        self.tabs.addTab(tab, QIcon.fromTheme("view-calendar-week"), _("Schedule"),
                         _("Blocking turns on by itself during these times. An end time earlier than the start "
                         "time runs past midnight into the next day."))

    def _build_protection_tab(self):
        tab = QWidget()
        v = QVBoxLayout(tab)
        box = QGroupBox(_("Password"))
        bv = QVBoxLayout(box)
        self.pw_label = QLabel()
        bv.addWidget(self.pw_label)
        self.pw_btn = QPushButton(_("Set password…"))
        self.pw_btn.clicked.connect(self.change_password)
        row = QHBoxLayout()
        row.addWidget(self.pw_btn)
        row.addStretch(1)
        bv.addLayout(row)
        bv.addWidget(note(_("With a password set, changing any setting, ending a session early and uninstalling all "
                          "ask for it. For a stronger lock, have someone you trust choose it and keep it from you.")))
        v.addWidget(box)

        box = QGroupBox(_("Lock"))
        bv = QVBoxLayout(box)
        self.strict = QCheckBox(_("Strict mode: while a block is running, nothing can be changed, even with the password"))
        bv.addWidget(self.strict)
        self.strict_pending = QLabel()
        self.strict_pending.setWordWrap(True)
        self.strict_pending.setStyleSheet("color: #b3261e; font-weight: 600;")
        self.strict_pending.hide()
        bv.addWidget(self.strict_pending)
        self.strict.toggled.connect(self._show_strict_pending)
        bv.addWidget(note(_("In strict mode you cannot end a session, edit lists or the schedule, or uninstall until "
                          "the block is over. The program files are also made read-only for its duration.")))
        v.addWidget(box)

        box = QGroupBox(_("Browsers"))
        bv = QVBoxLayout(box)
        self.require_ext = QCheckBox(_("Close any browser that is not running the FocusGuard extension during a block"))
        bv.addWidget(self.require_ext)
        self.harden = QCheckBox(_("Turn off private windows and encrypted DNS in Firefox and Chromium-based browsers"))
        bv.addWidget(self.harden)
        self.ext_label = note("")
        bv.addWidget(self.ext_label)
        bv.addWidget(note(_("The extension files are in {path}. See the README for how to add it to "
                            "Firefox and Chrome. Turn the first option on only after the extension is installed, "
                            "or your browser will be closed about 90 seconds into every block.").format(path="\u2066" + EXTENSION_DIR + "\u2069")))
        v.addWidget(box)
        v.addStretch(1)
        self.tabs.addTab(tab, QIcon.fromTheme("security-high"), _("Protection"),
                         _("How hard it is to switch FocusGuard off."))

    def _show_strict_pending(self):
        saved = bool(self.cfg and self.cfg["protection"]["strict"])
        now = self.strict.isChecked()
        self.strict_pending.setText(_("Strict mode will be turned ON when you press Apply changes.") if now and not saved else
                                    _("Strict mode will be turned off when you press Apply changes.") if saved and not now else "")
        self.strict_pending.setVisible(now != saved)

    def _confirm_strict(self) -> str:
        """'yes', 'off' (apply the rest with strict mode left off) or 'cancel'."""
        st = self.status or {}
        when = (_("A block is running now, until {time}: everything will be locked from now until then.").format(time=fmt_time(st['until']))
                if st.get("active") and st.get("until") else
                _("Everything will be locked during every block from now on, starting with the next one."))
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(_("FocusGuard"))
        box.setText(_("The Strict mode box in the Protection tab is ticked. Turn strict mode on?"))
        box.setInformativeText(when + _(" You will not be able to change settings, end the block or uninstall, "
                               "even with the password."))
        on = box.addButton(_("Turn strict mode on"), QMessageBox.ButtonRole.DestructiveRole)
        off = box.addButton(_("Keep it off, apply the rest"), QMessageBox.ButtonRole.AcceptRole)
        cancel = box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(off)
        box.setEscapeButton(cancel)
        box.exec()
        clicked = box.clickedButton()
        return "yes" if clicked is on else "off" if clicked is off else "cancel"

    def _yt_mode_changed(self):
        mode = self.yt_mode.currentData()
        self.yt_filter_panel.setVisible(mode == "filter")
        self.yt_off_note.setVisible(mode != "filter")
        self.yt_off_note.setText(_("During a block every YouTube page is blocked.") if mode == "block" else
                                 _("YouTube is left alone during a block, even if the Video and streaming "
                                 "website category is ticked."))

    def _build_phone_tab(self):
        tab = QWidget()
        v = QVBoxLayout(tab)
        box = QGroupBox(_("Link code"))
        bv = QVBoxLayout(box)
        self.link_code = QLabel()
        self.link_code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.link_code.setStyleSheet("font-family: monospace; font-size: 20pt; font-weight: 600; padding: 8px 0;")
        bv.addWidget(self.link_code)
        self.link_hint = note("")
        bv.addWidget(self.link_hint)
        row = QHBoxLayout()
        self.link_btn = QPushButton(QIcon.fromTheme("smartphone"), _("Link a phone"))
        self.link_btn.clicked.connect(self.link_phone)
        self.unlink_btn = QPushButton(QIcon.fromTheme("list-remove"), _("Unlink"))
        self.unlink_btn.clicked.connect(self.unlink_phone)
        row.addWidget(self.link_btn)
        row.addWidget(self.unlink_btn)
        row.addStretch(1)
        bv.addLayout(row)
        v.addWidget(box)
        self.link_status = QLabel()
        self.link_status.setWordWrap(True)
        v.addWidget(self.link_status)
        v.addWidget(note(_("When a phone is linked, this computer sends its schedule, block lists and session times to "
                         "the phone through the public ntfy.sh relay. Everything is encrypted with a key made from "
                         "the link code, so the relay cannot read it. Anyone who has the code can read it, so keep "
                         "the code private. Unlinking stops all sending.")))
        v.addStretch(1)
        self.tabs.addTab(tab, QIcon.fromTheme("smartphone"), _("Phone"),
                         _("Have the FocusGuard phone app follow this computer's blocks and schedule."))

    def _show_link(self):
        current = (self.cfg or {}).get("link")
        linked = bool(current)
        self.link_code.setVisible(linked)
        self.link_code.setText(link.format_code(current["code"]) if linked else "")
        self.link_hint.setText(_("Type this code into the FocusGuard app on your phone.") if linked
                               else _("No phone is linked. Linking creates a code to type into the phone app."))
        self.link_btn.setVisible(not linked)
        self.unlink_btn.setVisible(linked)
        phone = self.status.get("phone_link", {})
        if not linked:
            text = ""
        elif phone.get("last_error"):
            text = _("Not sending: ") + phone["last_error"]
            if phone.get("available") is False:
                text += _("\nInstall it with: sudo apt install python3-cryptography")
        elif phone.get("last_ok"):
            text = _("Last sent to the phone relay at {time}.").format(time=fmt_time(phone['last_ok']))
        else:
            text = _("Waiting to send the first update…")
        self.link_status.setText(text)

    def link_phone(self):
        resp = self._guarded("link_create")
        if resp and self.cfg is not None:
            self.cfg["link"] = {"code": resp["code"], "server": ""}
            self.refresh_status()

    def unlink_phone(self):
        if QMessageBox.question(self, _("FocusGuard"), _("Unlink the phone? It will stop following this computer.")) \
                != QMessageBox.StandardButton.Yes:
            return
        if self._guarded("link_remove") and self.cfg is not None:
            self.cfg["link"] = None
            self.refresh_status()

    # ---- schedule table helpers -----------------------------------------------------
    def _centered(self, widget) -> QWidget:
        holder = QWidget()
        lay = QHBoxLayout(holder)
        lay.setContentsMargins(6, 0, 6, 0)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(widget)
        holder.inner = widget
        return holder

    def _add_schedule_row(self, entry: dict):
        row = self.sched.rowCount()
        self.sched.insertRow(row)
        on = QCheckBox()
        on.setChecked(entry.get("enabled", True))
        self.sched.setCellWidget(row, 0, self._centered(on))
        self.sched.setCellWidget(row, 1, QLineEdit(entry.get("name", "")))
        for d in range(7):
            cb = QCheckBox()
            cb.setChecked(d in entry.get("days", []))
            self.sched.setCellWidget(row, 2 + d, self._centered(cb))
        for col, key in ((9, "start"), (10, "end")):
            edit = QTimeEdit(QTime.fromString(entry[key], "HH:mm"))
            # Left to right before the format is set, or Arabic layout shows 09:00 as 00:09.
            edit.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
            edit.setDisplayFormat("HH:mm")
            self.sched.setCellWidget(row, col, edit)

    def _read_schedules(self) -> list:
        out = []
        for row in range(self.sched.rowCount()):
            out.append({
                "enabled": self.sched.cellWidget(row, 0).inner.isChecked(),
                "name": self.sched.cellWidget(row, 1).text().strip(),
                "days": [d for d in range(7) if self.sched.cellWidget(row, 2 + d).inner.isChecked()],
                "start": self.sched.cellWidget(row, 9).time().toString("HH:mm"),
                "end": self.sched.cellWidget(row, 10).time().toString("HH:mm"),
            })
        return out

    # ---- apps helpers -----------------------------------------------------------------
    def _filter_apps(self, text: str):
        text = text.lower()
        for i in range(self.app_tree.topLevelItemCount()):
            item = self.app_tree.topLevelItem(i)
            item.setHidden(bool(text) and text not in item.text(0).lower() and text not in item.text(2).lower())

    def _covered(self, app: dict) -> bool:
        on = {k for k, cb in self.app_cat_boxes.items() if cb.isChecked()}
        return bool(on & set(app["categories"]))

    def _mark_category_apps(self):
        """Show each app's tick from its category, its own tick, or the user's exception."""
        self._app_sync = True
        try:
            for i in range(self.app_tree.topLevelItemCount()):
                item = self.app_tree.topLevelItem(i)
                app = item.data(0, Qt.ItemDataRole.UserRole)
                if self._covered(app):
                    allowed = app["id"] in self.app_allowed
                    blocked = not allowed
                    tip = (_("Allowed: an exception to its category. Tick to block it again.") if allowed
                           else _("Blocked through its category. Untick to allow this app."))
                else:
                    blocked = app["id"] in self.app_selected
                    tip = ""
                item.setCheckState(0, Qt.CheckState.Checked if blocked else Qt.CheckState.Unchecked)
                item.setToolTip(0, tip)
                exception = self._covered(app) and not blocked
                font = item.font(0)
                font.setItalic(exception)
                item.setFont(0, font)
                cats = ", ".join(_(config.APP_CATEGORIES[c].split(" ")[0]) for c in app["categories"])
                item.setText(1, _("{cats} (allowed)").format(cats=cats) if exception else cats)
        finally:
            self._app_sync = False

    def _app_ticked(self, item, column):
        if self._app_sync or column != 0:
            return
        app = item.data(0, Qt.ItemDataRole.UserRole)
        on = item.checkState(0) == Qt.CheckState.Checked
        if self._covered(app):
            (self.app_allowed.discard if on else self.app_allowed.add)(app["id"])
        else:
            (self.app_selected.add if on else self.app_selected.discard)(app["id"])
        self._mark_category_apps()

    # ---- load / save --------------------------------------------------------------------
    def load_config(self):
        try:
            resp = client.call("get_config")
        except client.ServiceError as exc:
            self.cfg = None
            self.message.setText(tr_message(str(exc)))
            return
        self.cfg = cfg = resp["config"]
        self.web_categories = resp["web_categories"]
        self.message.setText("")

        for key, cb in self.app_cat_boxes.items():
            cb.setChecked(key in cfg["apps"]["categories"])
        self.app_selected = {a["id"] for a in cfg["apps"]["selected"]}
        self.app_allowed = {a["id"] for a in cfg["apps"].get("allowed", [])}
        self._mark_category_apps()
        self.custom_names.setPlainText("\n".join(cfg["apps"]["custom_names"]))

        if not self.web_cat_boxes:
            for key, info in self.web_categories.items():
                cb = QCheckBox(_("{label}  ({n} sites)").format(label=_(info['label']), n=info['count']))
                self.web_cat_boxes[key] = cb
                self.web_box_layout.addWidget(cb)
        for key, cb in self.web_cat_boxes.items():
            cb.setChecked(key in cfg["web"]["categories"])
        self.custom_blocked.setPlainText("\n".join(cfg["web"]["custom_blocked"]))
        self.exceptions.setPlainText("\n".join(cfg["web"]["exceptions"]))

        yt = cfg["youtube"]
        self.yt_mode.setCurrentIndex(max(0, self.yt_mode.findData(yt["mode"])))
        self._yt_mode_changed()
        for cat, cb in self.yt_cat_boxes.items():
            cb.setChecked(cat in yt["allowed_categories"])
        self.yt_allow.setPlainText("\n".join(yt["allow_keywords"]))
        self.yt_block.setPlainText("\n".join(yt["block_keywords"]))
        self.yt_unknown.setChecked(yt["unknown"] == "block")
        self.yt_shorts.setChecked(yt["block_shorts"])

        self.sched.setRowCount(0)
        for entry in cfg["schedules"]:
            self._add_schedule_row(entry)

        prot = cfg["protection"]
        self.strict.setChecked(prot["strict"])
        self._show_strict_pending()
        self.require_ext.setChecked(prot["require_extension"])
        self.harden.setChecked(prot["harden_browsers"])
        self._show_password_state(cfg["has_password"])
        self._show_link()

    def _show_password_state(self, has: bool):
        self.pw_label.setText(_("A password is set.") if has else _("No password is set: anyone at this computer can change these settings."))
        self.pw_btn.setText(_("Change password…") if has else _("Set password…"))

    def collect(self) -> dict:
        selected, allowed = [], []
        keep = ("id", "name", "names", "flatpak", "snap")
        for i in range(self.app_tree.topLevelItemCount()):
            app = self.app_tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
            if not self._covered(app) and app["id"] in self.app_selected:
                selected.append({k: app[k] for k in keep})
            elif app["id"] in self.app_allowed:
                # Kept even while the category is off, so it still applies when the category is ticked again.
                allowed.append({k: app[k] for k in keep})
        return {
            "apps": {
                "categories": [k for k, cb in self.app_cat_boxes.items() if cb.isChecked()],
                "selected": selected,
                "allowed": allowed,
                "custom_names": lines(self.custom_names),
            },
            "web": {
                "categories": [k for k, cb in self.web_cat_boxes.items() if cb.isChecked()],
                "custom_blocked": lines(self.custom_blocked),
                "exceptions": lines(self.exceptions),
            },
            "youtube": {
                "mode": self.yt_mode.currentData(),
                "allowed_categories": [c for c, cb in self.yt_cat_boxes.items() if cb.isChecked()],
                "allow_keywords": lines(self.yt_allow),
                "block_keywords": lines(self.yt_block),
                "unknown": "block" if self.yt_unknown.isChecked() else "allow",
                "block_shorts": self.yt_shorts.isChecked(),
            },
            "schedules": self._read_schedules(),
            "protection": {
                "strict": self.strict.isChecked(),
                "require_extension": self.require_ext.isChecked(),
                "harden_browsers": self.harden.isChecked(),
            },
        }

    def ask_password(self) -> tuple[bool, str | None]:
        """(proceed, password). No prompt when no password is set."""
        if not self.status.get("has_password"):
            return True, None
        text, ok = QInputDialog.getText(self, _("FocusGuard"), _("Password:"), QLineEdit.EchoMode.Password)
        return ok, text

    def _guarded(self, cmd: str, **params) -> dict | None:
        ok, password = self.ask_password()
        if not ok:
            return None
        try:
            resp = client.call(cmd, password=password, **params)
        except client.ServiceError as exc:
            QMessageBox.critical(self, _("FocusGuard"), tr_message(str(exc)))
            return None
        if not resp.get("ok"):
            QMessageBox.warning(self, _("FocusGuard"), tr_message(client.error_text(resp)))
            return None
        return resp

    def apply(self):
        if self.cfg is None:
            self.load_config()
            return
        new = self.collect()
        bad = [d for d in new["web"]["custom_blocked"] + new["web"]["exceptions"] if not config.normalize_domain(d)]
        if bad:
            QMessageBox.warning(self, _("FocusGuard"), _("These do not look like website addresses:\n") + "\n".join(bad[:10]))
            return
        if new["protection"]["strict"] and not self.cfg["protection"]["strict"]:
            choice = self._confirm_strict()
            if choice == "cancel":
                return
            if choice == "off":
                self.strict.setChecked(False)
                new["protection"]["strict"] = False
        if self._guarded("set_config", config=new):
            self.load_config()
            self.message.setText(_("✓ Changes applied"))
            QTimer.singleShot(5000, lambda: self.message.text().startswith("✓") and self.message.setText(""))
            self.refresh_status()

    def change_password(self):
        dlg = PasswordDialog(self, bool(self.status.get("has_password")))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            resp = client.call("set_password", password=dlg.old.text() or None, new_password=dlg.new.text() or None)
        except client.ServiceError as exc:
            QMessageBox.critical(self, _("FocusGuard"), tr_message(str(exc)))
            return
        if not resp.get("ok"):
            QMessageBox.warning(self, _("FocusGuard"), tr_message(client.error_text(resp)))
            return
        self.refresh_status()
        self._show_password_state(bool(dlg.new.text()))

    def start_session(self, minutes: int):
        try:
            resp = client.call("start_session", minutes=minutes)
        except client.ServiceError as exc:
            QMessageBox.critical(self, _("FocusGuard"), tr_message(str(exc)))
            return
        if not resp.get("ok"):
            QMessageBox.warning(self, _("FocusGuard"), tr_message(client.error_text(resp)))
        self.refresh_status()

    def stop_session(self):
        if self._guarded("stop_session"):
            self.refresh_status()

    # ---- status ---------------------------------------------------------------------------
    def refresh_status(self):
        # Poll gently while hidden in the tray.
        self.timer.setInterval(3000 if self.isVisible() else 10000)
        try:
            self.status = st = client.call("status", timeout=5)["status"]
        except (client.ServiceError, KeyError) as exc:
            self.status = {}
            self.banner.setText(_("The FocusGuard service is not running"))
            self.detail.setText(tr_message(str(exc)) + _("\nStart it with: sudo systemctl start focusguard"))
            self._set_pill("down", _("NOT RUNNING"))
            return
        if self.cfg is None:
            self.load_config()
        if st["active"]:
            self.banner.setText(_("Blocking is on until {time}").format(time=fmt_time(st['until'])))
            self.pill.setToolTip(fmt_left(st["until"]))
            why = {"schedule": _("Your schedule turned it on."), "session": _("You started a focus session."),
                   "schedule and session": _("Your schedule and a focus session are both running.")}.get(st["reason"], "")
            if st["locked"]:
                why += _(" Strict mode: settings are locked until it ends.")
            self.detail.setText(f"{fmt_left(st['until']).capitalize()}. {why}".strip())
        else:
            self.banner.setText(_("Blocking is off"))
            self.detail.setText(_("Next scheduled block starts {time}.").format(time=fmt_time(st['next_start'])) if st["next_start"]
                                else _("Nothing is scheduled. Add time blocks on the Schedule tab or start a session below."))
        self._set_pill("on" if st["active"] else "off", _("FOCUS ON") if st["active"] else _("OFF"))
        cap, val = self.tiles["when"]
        cap.setText(_("Ends") if st["active"] else _("Next block"))
        val.setText(fmt_time(st["until"] if st["active"] else st["next_start"]) or _("Not scheduled"))
        if self.cfg:
            on = sum(1 for e in self.cfg["schedules"] if e["enabled"] and e["days"])
            self.tiles["schedule"][1].setText((_("1 time block") if on == 1 else _("{n} time blocks").format(n=on)) if on else _("None"))
        self.tiles["lock"][1].setText(_("Strict mode") if st["strict"] else _("Password") if st["has_password"] else _("None"))
        self.stop_btn.setEnabled(st["active"] and "session" in (st["reason"] or "") and not st["locked"])
        self.apply_btn.setEnabled(not st["locked"])
        names = {"firefox": "Firefox", "chrome": "Chrome", "chromium": "Chromium", "brave": "Brave",
                 "edge": "Edge", "opera": "Opera"}
        seen = [names.get(b, b) for b in st["extensions"]]
        self._show_link()
        self.tiles["extension"][1].setText(", ".join(seen) if seen else _("Not detected"))
        self.ext_label.setText(_("Extension currently running in: ") + ", ".join(seen) + "." if seen
                               else _("No browser extension has checked in during the last few minutes."))

        events = st.get("events", [])
        latest = events[-1]["seq"] if events else None
        if latest != self.drawn_event:  # redraw the list only when something new happened
            self.drawn_event = latest
            self.events.clear()
            for ev in reversed(events):
                d = datetime.fromtimestamp(ev["time"])
                self.events.addItem(f"{d.hour:02d}:{d.minute:02d}:{d.second:02d}  {tr_message(ev['message'])}")
        if events:
            if self.seen_event is not None and self.tray:
                for ev in events:
                    if ev["seq"] > self.seen_event and ev["message"].startswith(("Closed", "Blocking")):
                        self.tray.showMessage(_("FocusGuard"), tr_message(ev["message"]), QSystemTrayIcon.MessageIcon.Information, 5000)
            self.seen_event = latest
        if self.tray:
            self.tray.setToolTip(_("FocusGuard: ") + self.banner.text())

    def _language_picked(self):
        lang = self.lang_box.currentData()
        if lang == i18n.language():
            return
        try:
            i18n.save_language(lang)
        except OSError:
            pass  # still switch for this run
        if self.on_language:
            QTimer.singleShot(0, lambda: self.on_language(lang))

    def _set_pill(self, state: str, text: str):
        if self.pill.property("state") != state or self.pill.text() != text:
            self.pill.setText(text)
            self.pill.setProperty("state", state)
            self.pill.style().unpolish(self.pill)
            self.pill.style().polish(self.pill)

    def closeEvent(self, event):
        if self.tray and self.tray.isVisible():
            self.hide()
            event.ignore()
        else:
            event.accept()


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    QLocale.setDefault(QLocale(QLocale.Language.English, QLocale.Country.UnitedStates))  # Western digits in an English UI
    app = QApplication(argv)
    app.setApplicationName("FocusGuard")

    # Only one copy per user: a second launch asks the running one to show its window, then exits.
    channel = f"focusguard-gui-{os.getuid()}"
    probe = QLocalSocket()
    probe.connectToServer(channel)
    if probe.waitForConnected(500):
        probe.write(b"show" if "--tray" not in argv else b"noop")
        probe.waitForBytesWritten(500)
        probe.disconnectFromServer()
        return 0
    QLocalServer.removeServer(channel)  # clear a stale socket left by a crashed copy
    server = QLocalServer(app)
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    server.listen(channel)
    app.setDesktopFileName("focusguard")
    app.setQuitOnLastWindowClosed(False)
    tray = QSystemTrayIcon(QIcon.fromTheme("security-high"), app) if QSystemTrayIcon.isSystemTrayAvailable() else None
    if tray is None:
        app.setQuitOnLastWindowClosed(True)
    holder = {}

    def build(lang: str, previous=None):
        """Make the window (and tray menu) in a language; replaces the previous window if given."""
        i18n.set_language(lang)
        # Qt's own words (OK, Cancel, Yes, No) come from Qt's translation files when they are installed.
        if holder.get("qt_tr"):
            app.removeTranslator(holder.pop("qt_tr"))
        if lang != "en":
            qt_tr = QTranslator(app)
            if qt_tr.load(f"qtbase_{lang}", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
                app.installTranslator(qt_tr)
                holder["qt_tr"] = qt_tr
        app.setLayoutDirection(Qt.LayoutDirection.RightToLeft if i18n.is_rtl() else Qt.LayoutDirection.LeftToRight)
        window = MainWindow()
        window.on_language = lambda new_lang: build(new_lang, holder.get("window"))
        window.quit_btn.clicked.connect(app.quit)
        QShortcut(QKeySequence.StandardKey.Quit, window, activated=app.quit)
        if tray is not None:
            menu = QMenu()
            show = QAction(_("Open FocusGuard"), menu)
            show.triggered.connect(lambda: raise_window())
            menu.addAction(show)
            for minutes in (25, 50, 90):
                act = QAction(_("Start a {m} minute session").format(m=minutes), menu)
                act.triggered.connect(lambda _c=False, m=minutes: holder["window"].start_session(m))
                menu.addAction(act)
            menu.addSeparator()
            quit_act = QAction(QIcon.fromTheme("application-exit"), _("Quit FocusGuard (blocking keeps running)"), menu)
            quit_act.setShortcut(QKeySequence.StandardKey.Quit)
            quit_act.triggered.connect(app.quit)
            menu.addAction(quit_act)
            tray.setContextMenu(menu)
            window.tray = tray
            window._tray_menu = menu
        holder["window"] = window
        if previous is not None:
            window.restoreGeometry(previous.saveGeometry())
            window.tabs.setCurrentIndex(previous.tabs.nav.currentRow())
            if previous.isVisible():
                window.show()  # first, so the app never has zero windows in between
            previous.timer.stop()
            previous.tray = None  # so closing it really closes it
            previous.close()
            previous.deleteLater()
        return window

    if tray is not None:
        tray.activated.connect(lambda reason: raise_window() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        tray.show()
    window = build(i18n.load_language())

    def raise_window():
        window = holder["window"]
        window.show()
        window.setWindowState(window.windowState() & ~Qt.WindowState.WindowMinimized)
        window.raise_()
        window.activateWindow()

    def on_message():
        conn = server.nextPendingConnection()
        if conn is None:
            return
        conn.waitForReadyRead(500)
        if bytes(conn.readAll()) == b"show":
            raise_window()
        conn.deleteLater()

    server.newConnection.connect(on_message)

    if "--tray" not in argv or window.tray is None:
        window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
