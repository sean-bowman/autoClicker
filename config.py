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

# boxed.gg sits behind CloudFront, which 403s the default Playwright headless
# user-agent (it contains "HeadlessChrome"). Presenting a normal desktop Chrome
# UA clears the block — verified returning 202 vs. 403 with the default. Keep this
# roughly current with a real Chrome version.
USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36'
)

# Launch args that reduce automation fingerprinting. --disable-blink-features=
# AutomationControlled hides the navigator.webdriver flag many bot filters check.
BROWSER_ARGS = ['--disable-blink-features=AutomationControlled']

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
