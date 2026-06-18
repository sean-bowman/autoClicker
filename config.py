'''
Central configuration for the boxed.gg gem-drop claimer.

Every tunable lives here so the login, claim, and scheduling pieces share one
source of truth. Paths are resolved relative to this file so the scripts behave
identically whether launched by hand, by a .bat wrapper, or by Task Scheduler
(which sets an arbitrary working directory).
'''

from pathlib import Path

# -- Target ---------------------------------------------------------------- #

# The page that surfaces the hourly gem-drop pool. boxed.gg gates this behind
# login, so claim.py relies on the persisted browser profile to arrive here
# already authenticated.
BOXED_URL = 'https://boxed.gg/'

# How often Task Scheduler fires claim.py. The drop pool replenishes hourly per
# the project objective, so an hourly trigger is the default cadence. This value
# is consumed by setupTask.ps1 (in hours) and documented here for traceability.
CLAIM_INTERVAL_HOURS = 1

# -- Paths ----------------------------------------------------------------- #

# Directory of this file, used to anchor every other path.
BASE_DIR = Path(__file__).resolve().parent

# Persistent Chromium profile. Logging in once (via login.py) writes cookies and
# localStorage here; claim.py reuses it so it never has to handle the password.
# Gitignored: it contains live session credentials.
PROFILE_DIR = BASE_DIR / 'browserProfile'

# Runtime logs, per-run result lines, and failure screenshots/HTML dumps.
# Gitignored: pure runtime output.
LOG_DIR = BASE_DIR / 'logs'

# -- Behaviour ------------------------------------------------------------- #

# Run claim.py without a visible window by default (Task Scheduler context).
# Override to False for the headed discovery/debugging run via the --headed flag.
HEADLESS = True

# boxed.gg sits behind Cloudflare/CloudFront, which fingerprints automated
# browsers. Two independent defenses, both verified against the live site:
#
#   1. Drive REAL Google Chrome (channel below) rather than Playwright's bundled
#      "Chrome for Testing" build. Cloudflare's Turnstile challenge flags the
#      Testing build and leaves navigator.webdriver = true; real Chrome with the
#      automation switch stripped reports navigator.webdriver = false and clears
#      the human-verification step during manual login.
#   2. Strip the --enable-automation switch Playwright adds by default, and
#      disable the AutomationControlled blink feature.
#
# Set BROWSER_CHANNEL = None to fall back to Playwright's bundled Chromium (e.g.
# on a machine without Chrome installed); the USER_AGENT spoof below is then
# applied to dodge the headless 403. With a real channel we deliberately do NOT
# override the UA — Chrome's native UA must match its real fingerprint.
BROWSER_CHANNEL = 'chrome'  # or 'msedge'; None -> bundled Chromium

# Launch args that reduce automation fingerprinting.
BROWSER_ARGS = ['--disable-blink-features=AutomationControlled']

# Default switches to suppress. --enable-automation advertises automation to bot
# filters. --no-sandbox is injected by Playwright and triggers Chrome's yellow
# "unsupported command-line flag" security banner; dropping it lets Chrome run
# with its sandbox enabled (more secure) and removes the banner.
IGNORE_DEFAULT_ARGS = ['--enable-automation', '--no-sandbox']

# Fallback UA, used ONLY when BROWSER_CHANNEL is None. The bundled headless build
# otherwise sends "HeadlessChrome", which CloudFront 403s. Ignored for real Chrome.
USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36'
)


def launchOptions(headless: bool) -> dict:
    '''
    Build the keyword args shared by login.py and claim.py for
    launch_persistent_context, so both browsers present an identical fingerprint.

    Centralised on purpose: the manual login (login.py) and the scheduled claim
    (claim.py) MUST look like the same browser, or Cloudflare invalidates the
    clearance cookie the login earned.
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

# Seconds to wait for the page and its dynamic gem-drop widgets to settle before
# we start hunting for claimable elements. boxed.gg is a single-page app, so the
# claim controls hydrate after the initial document load.
PAGE_SETTLE_SECONDS = 8

# Candidate selectors for the claimable gem-drop control(s). boxed.gg's markup
# is only knowable from a logged-in session, so this list is populated during the
# guided discovery run (see README "Tuning selectors"). claim.py tries each in
# order and clicks every match it finds enabled, so over-inclusive entries are
# harmless. Ordered most-specific first.
CLAIM_SELECTORS = [
    # Placeholder candidates — refined during discovery against the live DOM.
    'button:has-text("Claim")',
    'button:has-text("Collect")',
    '[data-testid*="claim" i]',
    '[class*="claim" i] button',
]

# A selector that, when present, signals we are NOT logged in (e.g. a visible
# "Log in" / "Sign in" control). claim.py uses this to fail fast with a clear
# "session expired, re-run login.py" message instead of silently clicking nothing.
LOGGED_OUT_SELECTOR = 'button:has-text("Log in"), button:has-text("Sign in"), a:has-text("Log in")'
