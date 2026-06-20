'''
Central configuration for the boxed.gg gem-drop claimer.

Every tunable lives here so the login, claim, and scheduling pieces share one
source of truth. Paths are resolved relative to this file so the scripts behave
identically whether launched by hand, by a .bat wrapper, or by Task Scheduler
(which sets an arbitrary working directory).
'''

from pathlib import Path

# -- Target ---------------------------------------------------------------- #

# The page that surfaces the gem-drop chat overlay. boxed.gg gates this behind
# login, so the watcher relies on the persisted browser profile to arrive here
# already authenticated.
BOXED_URL = 'https://boxed.gg/'

# -- Paths ----------------------------------------------------------------- #

# Directory of this file, used to anchor every other path.
BASE_DIR = Path(__file__).resolve().parent

# Persistent Chrome profile. Logging in once (via login.py) writes cookies and
# localStorage here; the watcher reuses it so it never has to handle the password.
# Gitignored: it contains live session credentials.
PROFILE_DIR = BASE_DIR / 'browserProfile'

# Runtime logs, per-run result lines, and screenshots. Gitignored.
LOG_DIR = BASE_DIR / 'logs'

# Name of the Windows Scheduled Task that runs the watcher in the background
# (registered by setupTask.ps1). The control GUI (control.py) toggles this task
# on and off, so both read the name from here.
TASK_NAME = 'BoxedGemWatcher'

# boxed.gg sits behind Cloudflare/CloudFront, which fingerprints automated
# browsers. Two independent defenses, both verified against the live site:
#
#   1. Drive REAL Google Chrome (channel below) rather than Playwright's bundled
#      "Chrome for Testing" build, which Cloudflare's Turnstile challenge flags.
#   2. Strip the --enable-automation switch Playwright adds by default.
#   3. Force navigator.webdriver to undefined via an init script (STEALTH_INIT_
#      SCRIPT below) rather than the --disable-blink-features=AutomationControlled
#      command-line flag. Both achieve webdriver=false (which Cloudflare reads),
#      but the flag triggers Chrome's yellow "unsupported command-line flag"
#      banner, whereas the init script is invisible.
#
# Set BROWSER_CHANNEL = None to fall back to Playwright's bundled Chromium (e.g.
# on a machine without Chrome installed); the USER_AGENT spoof below is then
# applied to dodge the headless 403. With a real channel we deliberately do NOT
# override the UA -- Chrome's native UA must match its real fingerprint.
BROWSER_CHANNEL = 'chrome'  # or 'msedge'; None -> bundled Chromium

# Extra launch args. Empty by default: the only fingerprint we need to mask
# (navigator.webdriver) is handled by STEALTH_INIT_SCRIPT to avoid Chrome's
# unsupported-flag banner. Add args here only if they don't surface that banner.
BROWSER_ARGS: list[str] = []

# Default switches to suppress. --enable-automation advertises automation to bot
# filters. --no-sandbox is injected by Playwright and triggers Chrome's yellow
# "unsupported command-line flag" security banner; dropping it lets Chrome run
# with its sandbox enabled (more secure) and removes the banner.
IGNORE_DEFAULT_ARGS = ['--enable-automation', '--no-sandbox']

# Injected before any page script runs. Cloudflare's challenge reads
# navigator.webdriver to detect automation; real Chrome under Playwright reports
# true, so we redefine it as undefined to look like an ordinary browser.
STEALTH_INIT_SCRIPT = (
    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
)

# Fallback UA, used ONLY when BROWSER_CHANNEL is None. The bundled headless build
# otherwise sends "HeadlessChrome", which CloudFront 403s. Ignored for real Chrome.
USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36'
)

def launchOptions(headless: bool) -> dict:
    '''
    Build the keyword args shared by login.py and watch.py for
    launch_persistent_context, so both browsers present an identical fingerprint.

    Centralised on purpose: the manual login (login.py) and the watcher (watch.py)
    MUST look like the same browser, or Cloudflare invalidates the clearance cookie
    the login earned.
    '''
    options: dict = {
        'user_data_dir': str(PROFILE_DIR),
        'headless': headless,
        'args': BROWSER_ARGS,
        'ignore_default_args': IGNORE_DEFAULT_ARGS,
        'viewport': {'width': 1280, 'height': 900},
    }
    if BROWSER_CHANNEL:
        # Real Chrome: use its native UA/fingerprint, do not spoof.
        options['channel'] = BROWSER_CHANNEL
    else:
        # Bundled Chromium fallback: spoof UA to clear the headless 403.
        options['user_agent'] = USER_AGENT
    return options

def applyStealth(context) -> None:
    '''
    Apply the navigator.webdriver override to a freshly launched context.

    Kept separate from launchOptions() because add_init_script is a method on the
    context, not a launch argument. Both login.py and watch.py call this so they
    present an identical, non-automated fingerprint to Cloudflare.
    '''
    context.add_init_script(STEALTH_INIT_SCRIPT)

# Seconds to wait for the page and its dynamic gem-drop widgets to settle before
# we start hunting for claimable elements. boxed.gg is a single-page app, so the
# claim controls hydrate after the initial document load.
PAGE_SETTLE_SECONDS = 8

# -- Gem-drop overlay (chat) ----------------------------------------------- #

# On boxed.gg the drop lives in the chat overlay. Between drops the widget shows
# an "INCOMING / Gem Drop" header with a visual (non-textual) countdown; when a
# drop goes live a panel expands containing a "Gem drop is now LIVE!" message and
# the claim button below. The claim button is injected into the DOM only during
# the claim window, so the watcher keys on its PRESENCE rather than the countdown.
#
# The claim button is text-labeled; clicking it enters the drop ("Join to earn
# free gems!"). A successful join removes the button from the widget.
CLAIM_BUTTON_TEXT = 'Count Me In!'

# A selector that, when present, signals we are NOT logged in. Used to fail fast
# with a clear "session expired, re-run login.py" message.
LOGGED_OUT_SELECTOR = 'button:has-text("Log in"), button:has-text("Sign in"), a:has-text("Log in")'

# -- Watcher --------------------------------------------------------------- #

# Seconds between polls of the drop state. Drops are ~30 min apart but the live
# window can be as short as ~10 s, so poll briskly to catch it early.
POLL_INTERVAL_SECONDS = 2

# Randomised, human-like delay (seconds) before clicking the claim once it goes
# live -- the click should not be robotically instantaneous. Kept comfortably
# inside the live window, which can be as short as ~10 s. The watcher re-checks
# that the drop is still live after the delay, so an over-long delay just misses
# that drop rather than erroring; widen if you want more variance and accept that.
CLICK_DELAY_RANGE = (1.0, 4.0)

# Reload the page if it has been open this long, to shed memory and keep the
# Cloudflare clearance fresh while idle between drops.
WATCH_RELOAD_EVERY_MINUTES = 25

# The watcher runs real (headed) Chrome positioned off-screen. Headless real
# Chrome is Cloudflare-blocked AND fails to reuse the logged-in profile (exit 21),
# so an off-screen headed window is the practical "invisible" mode.
WATCH_HEADLESS = False
WINDOW_OFFSCREEN_ARG = '--window-position=-32000,-32000'
