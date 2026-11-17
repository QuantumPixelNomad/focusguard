# FocusGuard 0.3.0

What changed since 0.2.0
- **Arabic.** Choose English or العربية in the Language list at the bottom of the window. The window switches straight away, to a right-to-left layout for Arabic, and remembers your choice.
- Apps inside a blocked category can be allowed one by one. In the Applications tab, tick a category and its apps are ticked for you; untick an app to keep it allowed. Allowing Steam, Lutris, Heroic or Bottles also allows the games they start. An app you tick on its own, or a process name you type, is always blocked.
- Two new app categories: Social media apps and News and feed readers. "Social and chat apps" is now "Chat and messaging apps", and more apps are recognised.
- Strict mode can no longer be switched on by surprise: a red line under the checkbox warns before Apply, and the confirmation's default button is "Keep it off, apply the rest".
- Your current settings carry over unchanged.

Install (over any earlier version)
    tar xzf focusguard-0.3.0.tar.gz
    cd focusguard
    sudo ./install.sh
Then quit FocusGuard from the tray and open it again.

Installing does not change your settings, so if strict mode is on it stays on. To switch it off during a block, use the three commands in the README under "Strict mode turned on by mistake?".
