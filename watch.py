'''
Continuous gem-drop watcher for boxed.gg.

boxed.gg drops a gem pool roughly every 30 minutes, but the claim control only
exists for a short window around each drop. A scheduled one-shot can't reliably
land in that window, so this watcher keeps one browser open, polls the chat
gem-drop widget, and clicks the claim button the instant it appears — after a
small randomised human-like delay so the click isn't robotically instantaneous.

It runs real (headed) Chrome positioned off-screen: headless real Chrome is
blocked by Cloudflare and won't reuse the logged-in profile, so off-screen is the
practical 'invisible' mode. The browser is relaunched automatically if it dies,
and the page is periodically reloaded to stay fresh.

Usage:
    python watch.py                 # run forever (the scheduled mode)
    python watch.py --minutes 40    # run for a bounded time (testing)
    python watch.py --observe       # log drop state, never click (discovery)
    python watch.py --visible       # show the window instead of off-screen
'''

import argparse
import random
import sys
import time
from datetime import datetime
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
import config

def log(message: str) -> None:
    '''Append a timestamped line to the watcher log and echo to stdout.'''
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] {message}'
    print(line, flush=True)
    with open(config.LOG_DIR / 'watch.log', 'a', encoding='utf-8') as fh:
        fh.write(line + '\n')

def claimButton(page):
    '''Locator for the live claim button (text-anchored, so it scopes itself).'''
    return page.get_by_role('button', name=config.CLAIM_BUTTON_TEXT, exact=True)

# The claim button renders at the top of the chat, behind the full-width sticky
# nav (z-40) whose icon-buttons intercept ordinary clicks; and the site ignores
# synthetic (untrusted) clicks. So to claim we momentarily hide the nav (the
# button reflows into the clear), confirm the button is now the topmost element
# at its centre, and report the coordinate for a real trusted mouse click. The
# button is measured fresh each time because the live progress bar re-renders it
# constantly — a cached node goes stale. arguments[0] is the button text.
_REVEAL_CLAIM_JS = '''(text) => {
    const nav = document.querySelector('#top-nav--desktop');
    if (nav) { window.__nav = nav; window.__navDisplay = nav.style.display; nav.style.setProperty('display', 'none', 'important'); }
    const b = [...document.querySelectorAll('button')].find(x => (x.textContent || '').trim() === text);
    if (!b) return null;
    const r = b.getBoundingClientRect();
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    return {cx, cy, ok: document.elementFromPoint(cx, cy) === b};
}'''

_RESTORE_NAV_JS = '''() => { if (window.__nav) window.__nav.style.display = window.__navDisplay || ''; }'''

def isClaimable(page) -> bool:
    '''True when the claim button is present, visible, and enabled.'''
    button = claimButton(page)
    if not button.count():
        return False
    first = button.first
    try:
        return first.is_visible() and first.is_enabled()
    except PlaywrightTimeoutError:
        return False

def isLoggedOut(page) -> bool:
    '''True when a login control is visible (session expired).'''
    try:
        return page.locator(config.LOGGED_OUT_SELECTOR).first.is_visible(timeout=2000)
    except PlaywrightTimeoutError:
        return False

def claimNow(page) -> bool:
    '''
    Click the claim button after a randomised delay. Returns True on a click.

    The delay (config.CLICK_DELAY_RANGE) keeps the action human-like; the live
    window is far longer than the delay, so we stay well inside it.
    '''
    low, high = config.CLICK_DELAY_RANGE
    delay = random.uniform(low, high)
    log(f'Drop is LIVE — claiming in {delay:.1f}s')
    time.sleep(delay)
    try:
        point = page.evaluate(_REVEAL_CLAIM_JS, config.CLAIM_BUTTON_TEXT)
        if not point or not point.get('ok'):
            log('Claim aborted: could not reveal claim button')
            return False
        page.mouse.click(point['cx'], point['cy'])   # trusted in-place click
    except Exception as exc:
        log(f'Claim click failed: {exc!r}'[:160])
        return False
    finally:
        try:
            page.evaluate(_RESTORE_NAV_JS)
        except Exception:
            pass
    # Success shows as the claim button disappearing (or disabling).
    time.sleep(1.0)
    joined = not isClaimable(page)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    try:
        page.screenshot(path=str(config.LOG_DIR / f'claim_{stamp}.png'))
    except Exception:
        pass
    log('Claimed — joined the drop' if joined else 'Clicked, but button still present (claim unconfirmed)')
    return joined

def watchSession(pw, headless: bool, offscreen: bool, observe: bool, deadline: float) -> str:
    '''
    Open one browser session and watch until the deadline or a fatal error.

    Returns a reason string: 'deadline' (time's up, stop) or 'relaunch' (the
    session died and the caller should open a fresh one).
    '''
    opts = config.launchOptions(headless=headless)
    if offscreen:
        opts['args'] = opts.get('args', []) + [config.WINDOW_OFFSCREEN_ARG]
    context = pw.chromium.launch_persistent_context(**opts)
    config.applyStealth(context)
    page = context.pages[0] if context.pages else context.new_page()
    try:
        page.goto(config.BOXED_URL, wait_until='domcontentloaded', timeout=45000)
        page.wait_for_timeout(config.PAGE_SETTLE_SECONDS * 1000)
        log('session up' + (' (observe mode)' if observe else ''))
        armed = True            # False after we claim, until the button disappears
        loggedOutStreak = 0
        nextReload = time.time() + config.WATCH_RELOAD_EVERY_MINUTES * 60
        while time.time() < deadline:
            try:
                if isClaimable(page):
                    if observe:
                        log('observe: drop is LIVE (would claim)')
                    elif armed:
                        if claimNow(page):
                            armed = False   # don't re-click the same drop
                    loggedOutStreak = 0
                else:
                    armed = True            # button gone -> ready for next drop
                    if isLoggedOut(page):
                        loggedOutStreak += 1
                        if loggedOutStreak in (1, 20):  # log first and persistent
                            log('SESSION EXPIRED — re-run login.py to refresh login')
                    else:
                        loggedOutStreak = 0
                # Periodic reload to shed memory and keep clearance fresh.
                if time.time() > nextReload:
                    page.goto(config.BOXED_URL, wait_until='domcontentloaded', timeout=45000)
                    page.wait_for_timeout(config.PAGE_SETTLE_SECONDS * 1000)
                    nextReload = time.time() + config.WATCH_RELOAD_EVERY_MINUTES * 60
            except PlaywrightTimeoutError as exc:
                log(f'transient timeout: {exc!r}'[:160])
            time.sleep(config.POLL_INTERVAL_SECONDS)
        return 'deadline'
    except Exception as exc:
        log(f'session error, relaunching: {exc!r}'[:200])
        return 'relaunch'
    finally:
        try:
            context.close()
        except Exception:
            pass

def parseArgs() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Watch boxed.gg and claim gem drops.')
    parser.add_argument('--minutes', type=float, default=None,
                        help='Stop after N minutes (default: run forever).')
    parser.add_argument('--observe', action='store_true',
                        help='Log drop state but never click (discovery).')
    parser.add_argument('--visible', action='store_true',
                        help='Show the browser window instead of positioning it off-screen.')
    return parser.parse_args()

def main() -> int:
    args = parseArgs()
    if not config.PROFILE_DIR.exists():
        log('No browser profile found — run login.py first.')
        return 2
    deadline = time.time() + args.minutes * 60 if args.minutes else float('inf')
    log(f'watcher starting (poll {config.POLL_INTERVAL_SECONDS}s, '
        f'delay {config.CLICK_DELAY_RANGE[0]}-{config.CLICK_DELAY_RANGE[1]}s)')
    with sync_playwright() as pw:
        while time.time() < deadline:
            reason = watchSession(pw, headless=config.WATCH_HEADLESS,
                                  offscreen=not args.visible, observe=args.observe,
                                  deadline=deadline)
            if reason == 'deadline':
                break
            time.sleep(5)   # brief backoff before relaunching a dead session
    log('watcher stopped')
    return 0

if __name__ == '__main__':
    sys.exit(main())
