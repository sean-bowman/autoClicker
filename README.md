# autoClicker — boxed.gg gem-drop claimer

A small, scheduled browser-automation utility that logs into [boxed.gg](https://boxed.gg),
and on an hourly cadence claims the gem-drop pool that replenishes each hour — so the drops
get collected without me sitting at the screen.

Built with [Playwright](https://playwright.dev/python/) driving a real Chromium instance.
A one-time manual login persists the session to disk; from then on a headless one-shot script,
fired by Windows Task Scheduler, does the claiming.

---

## How it works

The design separates the human step (logging in) from the automated step (claiming), and keeps
the session alive between runs with a persistent browser profile:

1. **`login.py`** — opens a visible browser once. You log in by hand (email + password, plus any
   captcha/2FA). Closing the window persists cookies and `localStorage` into `browserProfile/`.
2. **`claim.py`** — the scheduled one-shot. It reuses `browserProfile/` to arrive on boxed.gg
   already authenticated, clicks every available claim control, logs the outcome, and exits. It is
   idempotent — running it when nothing is claimable is a harmless no-op.
3. **Windows Task Scheduler** — runs `claim.py` (via `runClaim.bat`) once an hour. `setupTask.ps1`
   registers the task.

```
login.py  --(persists session)-->  browserProfile/
                                          |
Task Scheduler --hourly--> runClaim.bat --> claim.py --> claims drops + logs/
```

Keeping the password out of the codebase entirely (it lives only in the browser session you create)
is deliberate: nothing sensitive is ever written to a tracked file.

---

## Setup

Requires Python 3.10+ and a **real Google Chrome install** (see
[Beating Cloudflare](#beating-cloudflare) for why the bundled browser isn't enough).

```bash
pip install -r requirements.txt
playwright install chromium   # fallback browser, if Chrome is unavailable
```

**1. Log in once:**

```bash
python login.py
```

A browser opens on boxed.gg. Log in, then close the window. The session is saved.

**2. Verify a claim run:**

```bash
python claim.py --headed        # watch it work
python claim.py                 # headless, as it will run scheduled
```

Check `logs/claim.log` for the result line.

**3. Schedule it (run once, from an elevated PowerShell):**

```powershell
powershell -ExecutionPolicy Bypass -File .\setupTask.ps1
schtasks /run /tn BoxedGemClaimer   # fire a test run immediately
```

---

## Tuning selectors

boxed.gg renders its claim controls client-side, behind login, so the exact selectors are
discovered against the live DOM rather than guessed. `config.py` holds a `CLAIM_SELECTORS` list;
`claim.py` tries each in order and clicks every visible, enabled match.

To refine them, run a headed pass that stays open so you can inspect the page:

```bash
python claim.py --headed --keep-open
```

On any pass where nothing is claimed, `claim.py` saves a full-page screenshot and an HTML dump to
`logs/` — open those to find the right selector and add it to `CLAIM_SELECTORS`.

---

## Beating Cloudflare

boxed.gg sits behind Cloudflare, which actively fingerprints automated browsers. Two things were
needed to get through:

- **Drive real Google Chrome, not Playwright's bundled "Chrome for Testing".** The Testing build
  leaves `navigator.webdriver = true` and trips Cloudflare's human-verification challenge. Pointing
  Playwright at the installed Chrome (`channel='chrome'`) and stripping the `--enable-automation`
  switch reports `navigator.webdriver = false` and clears the challenge during manual login.
- **Run headed when challenged.** Headless Chrome reliably gets a `403` from Cloudflare even with a
  real-Chrome fingerprint. So `claim.py` starts headless (silent) and, if it detects a block,
  **automatically retries with a visible window** — which clears the managed challenge using the
  trust already established on the persisted profile. If even the headed retry is blocked, it tells
  you to re-run `login.py` to refresh the clearance cookie.

All of this lives in `config.launchOptions()`; set `BROWSER_CHANNEL = None` to fall back to bundled
Chromium (which then uses a spoofed user-agent to dodge the headless `403`).

## Configuration

All tunables live in [`config.py`](config.py): target URL, claim cadence, the persistent-profile
and log paths, page-settle timing, the selector list, and the browser-channel / fingerprint options.

---

## Project layout

| File | Role |
|------|------|
| `config.py` | Central configuration (URL, paths, selectors, timing) |
| `login.py` | One-time interactive login; persists the session |
| `claim.py` | One-shot headless claimer (the scheduled job) |
| `runClaim.bat` | Wrapper Task Scheduler invokes |
| `setupTask.ps1` | Registers the hourly scheduled task |
| `legacy/autoClickerScreenMatch.py` | The original v1 approach (see below) |

---

## v1 — the screen-matching approach

The first version (`legacy/autoClickerScreenMatch.py`) took a fundamentally different tack:
OS-level screen automation with `pyautogui` + OpenCV template matching. It screenshotted the
desktop, looked for a captured button image with `cv2.matchTemplate`, and clicked wherever it
matched. It worked, but was fragile — dependent on screen resolution, window position, and a
pre-captured template image, and blind to anything happening off the active screen.

The current version replaces that with browser automation: it operates on the DOM directly, runs
headless, survives in the background, and is driven by the page's actual structure rather than its
pixels. Kept here for provenance.

---

## Notes

This automates actions on my own boxed.gg account; it may conflict with the site's terms of service.
Use at your own discretion.
