# autoClicker — boxed.gg gem-drop watcher

A browser-automation utility that logs into [boxed.gg](https://boxed.gg) and continuously claims
the gem drops that go live in the chat overlay roughly every 30 minutes — so the drops get
collected without me sitting at the screen.

Built with [Playwright](https://playwright.dev/python/) driving a real, off-screen Google Chrome.
A one-time manual login persists the session to disk; from then on a long-running watcher claims
each drop the moment it appears, after a small randomised delay.

---

## How it works

The drop is surfaced in a chat overlay: between drops a header counts down; when a drop goes live,
a panel expands with a **"Count Me In!"** button that exists only for a short window. A scheduled
one-shot can't reliably land in that window, so this uses a continuous watcher instead.

1. **`login.py`** — opens a visible browser once. You log in by hand (email + password, plus any
   captcha / Cloudflare check). Closing the window persists cookies and `localStorage` into
   `browserProfile/`.
2. **`watch.py`** — the watcher. It reuses `browserProfile/` to arrive already authenticated, keeps
   the page open, polls the gem-drop widget, and clicks the claim button the instant it goes live —
   after a randomised human-like delay. It self-heals (reloads periodically, relaunches on crash,
   warns if the session expires).
3. **Windows Task Scheduler** — starts `watch.py` (via `runWatch.bat`) at logon and restarts it if
   it dies. `setupTask.ps1` registers the task.

```text
login.py  --(persists session)-->  browserProfile/
                                          |
Task Scheduler --at logon--> runWatch.bat --> watch.py (runs continuously) --> claims drops + logs/
```

The password never touches the codebase — it lives only in the browser session you create, so
nothing sensitive is written to a tracked file.

---

## Setup

Requires Python 3.10+ and a **real Google Chrome install** (see
[Beating Cloudflare](#beating-cloudflare) for why the bundled browser isn't enough).

```bash
pip install -r requirements.txt
playwright install chromium   # fallback browser, only if Chrome is unavailable
```

**1. Log in once:**

```bash
python login.py
```

A browser opens on boxed.gg. Log in, then close the window. The session is saved.

**2. Try the watcher:**

```bash
python watch.py --visible --minutes 35   # visible window, runs through one drop
python watch.py --observe                # log drop state but never click (discovery)
python watch.py                          # off-screen, runs forever (scheduled mode)
```

Watch `logs/watch.log` for `Drop is LIVE — claiming …` / `Claimed — joined the drop`, and the
`claim_*.png` proof screenshots.

**3. Schedule it (run once, from an elevated PowerShell):**

```powershell
powershell -ExecutionPolicy Bypass -File .\setupTask.ps1
schtasks /run /tn BoxedGemWatcher    # start it now without logging out
```

---

## Beating Cloudflare

boxed.gg sits behind Cloudflare, which actively fingerprints automated browsers. Getting through
took three things, all in `config.launchOptions()` / `config.applyStealth()`:

- **Drive real Google Chrome, not Playwright's bundled "Chrome for Testing."** The Testing build
  leaves `navigator.webdriver = true` and trips Cloudflare's human-verification challenge. Pointing
  Playwright at the installed Chrome (`channel='chrome'`) clears it.
- **Strip the automation tells.** Remove the `--enable-automation` switch and redefine
  `navigator.webdriver` to `undefined` via an init script (rather than the
  `--disable-blink-features` flag, which trips Chrome's unsupported-flag banner).
- **Run headed, off-screen.** Headless Chrome reliably gets a `403` even with a real-Chrome
  fingerprint, so the watcher runs a real window positioned at `-32000,-32000` — invisible, but
  fully rendered so Cloudflare is satisfied.

Set `BROWSER_CHANNEL = None` to fall back to bundled Chromium (which then uses a spoofed user-agent
to dodge the headless `403`).

---

## Clicking the claim button

Two quirks made the claim click non-trivial, handled in `watch.py`:

- The button sits at the top of the chat **behind the full-width sticky nav** (z-40), whose
  icon-buttons intercept ordinary clicks. The watcher momentarily hides the nav so the button
  reflows into the clear, then clicks it in place.
- The site **ignores synthetic (untrusted) clicks**, and the live progress bar **re-renders the
  button constantly** (so a cached element node goes stale). The watcher therefore measures the
  button fresh and delivers a real, trusted `mouse.click` at its coordinate. Success is confirmed by
  the button disappearing from the widget.

---

## Configuration

All tunables live in [`config.py`](config.py): target URL, profile/log paths, the claim button text,
poll interval, the randomised click-delay range, reload cadence, and the browser-channel /
fingerprint options.

---

## Project layout

| File | Role |
|------|------|
| `config.py` | Central configuration and launch/fingerprint options |
| `login.py` | One-time interactive login; persists the session |
| `watch.py` | The continuous gem-drop watcher (default; `--observe`, `--visible`, `--minutes`) |
| `runWatch.bat` | Wrapper Task Scheduler invokes |
| `setupTask.ps1` | Registers the logon-triggered, auto-restarting task |
| `legacy/autoClickerScreenMatch.py` | The original v1 approach (see below) |

---

## v1 — the screen-matching approach

The first version (`legacy/autoClickerScreenMatch.py`) took a fundamentally different tack:
OS-level screen automation with `pyautogui` + OpenCV template matching. It screenshotted the
desktop, looked for a captured button image with `cv2.matchTemplate`, and clicked wherever it
matched. It worked, but was fragile — dependent on screen resolution, window position, and a
pre-captured template image, and blind to anything off the active screen.

The current version replaces that with browser automation: it operates on the DOM directly, runs
invisibly in the background, and is driven by the page's actual structure rather than its pixels.
Kept here for provenance.

---

## Notes

This automates actions on my own boxed.gg account; it may conflict with the site's terms of service.
Use at your own discretion.
