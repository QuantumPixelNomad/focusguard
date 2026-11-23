# FocusGuard 0.3.1

What changed since 0.3.0
- **WhatsApp keeps working during blocks.** `web.whatsapp.com` is no longer in the Social media website list. WhatsApp desktop apps such as ZapFast and WhatsApp for Linux need that address to connect at all, so blocking it cut off WhatsApp messaging, not just a website. The rest of Social media is blocked as before. If you do want WhatsApp blocked, add `web.whatsapp.com` to your own blocked sites on the Websites tab.
- **Upgrading during a strict block.** The installer still stops during a strict block, but now tells you that `sudo ./install.sh --during-block` upgrades anyway. Your settings, the running block and strict mode all stay as they are.
- Your current settings carry over unchanged.

Install (over any earlier version)
    tar xzf focusguard-0.3.1.tar.gz
    cd focusguard
    sudo ./install.sh
Then quit FocusGuard from the tray and open it again.

If a strict block is running, use `sudo ./install.sh --during-block` instead. The new website list takes effect within a few seconds, and WhatsApp reconnects.
