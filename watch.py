'''
Continuous gem-drop watcher for boxed.gg.

boxed.gg drops a gem pool roughly every 30 minutes, but the claim control only
exists for a short window around each drop. A scheduled one-shot can't reliably
land in that window, so this watcher keeps one browser open, polls the chat
gem-drop widget, and clicks the claim button the instant it appears: after a
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
    python watch.py --probe-balance # dump candidate balance elements and exit
'''

import argparse
import json
import os
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
    # Under pythonw.exe (the scheduled, windowless mode) sys.stdout is None, so a
    # bare print would crash: guard it. The file log is the durable record.
    try:
        print(line, flush=True)
    except Exception:
        pass
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
# constantly -- a cached node goes stale. arguments[0] is the button text.
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

# Between drops the claim button stays in the DOM but its panel is collapsed to
# height 0 (overflow:hidden) -- and Playwright's is_visible() returns True for it
# anyway, because it ignores overflow-clipping. So we judge "claimable" by whether
# the button is actually un-clipped: every overflow:hidden ancestor must have real
# height and contain the button's centre. Collapsed panel -> not claimable.
_CLAIMABLE_JS = '''(text) => {
    const b = [...document.querySelectorAll('button')].find(x => (x.textContent || '').trim() === text);
    if (!b || b.disabled) return false;
    const br = b.getBoundingClientRect();
    if (br.width < 5 || br.height < 5) return false;
    const cy = br.top + br.height / 2;
    let p = b.parentElement;
    for (let i = 0; i < 15 && p; i++) {
        const cs = getComputedStyle(p);
        if (cs.overflow === 'hidden' || cs.overflowX === 'hidden' || cs.overflowY === 'hidden') {
            const pr = p.getBoundingClientRect();
            if (pr.height < 20) return false;            // collapsed panel
            if (cy < pr.top || cy > pr.bottom) return false;  // clipped out of view
        }
        p = p.parentElement;
    }
    return true;
}'''

def isClaimable(page) -> bool:
    '''True only when the claim button is present and genuinely un-clipped (live).'''
    try:
        return bool(page.evaluate(_CLAIMABLE_JS, config.CLAIM_BUTTON_TEXT))
    except PlaywrightTimeoutError:
        return False

def isLoggedOut(page) -> bool:
    '''True when a login control is visible (session expired).'''
    try:
        return page.locator(config.LOGGED_OUT_SELECTOR).first.is_visible(timeout=2000)
    except PlaywrightTimeoutError:
        return False

# Locate the account balance within the nav scope (see config.ACCOUNT_BALANCE_
# SCOPE for why a plain selector won't do). We identify the gem balance by WHAT
# it is, not by its digit-shape -- a comma or multi-digit text is not a reliable
# discriminator, since the shard counter can grow to a multi-digit number too:
#   Primary: the gem-amount component. Its CSS-module class carries the source
#     identifier 'gemAmount' (only the trailing build hash changes), so it's
#     unambiguous regardless of how many digits the balance has.
#   Fallback (class renamed in a rebuild): the first on-screen nav number that is
#     NOT inside the shard counter's subtree, so the two currencies can't be
#     confused. A >=2-digit guard here keeps stray single-digit badges out.
# Either way we return the full text only on an exact /^\d{1,3}(,\d{3})*$/ match,
# so a mid-animation partial render yields null rather than a wrong number.
_BALANCE_JS = r'''(a) => {
    const scope = document.querySelector(a.scope);
    if (!scope) return null;
    const re = /^\d{1,3}(,\d{3})*$/;
    const vw = window.innerWidth;
    const shard = a.shard ? scope.querySelector(a.shard) : null;
    function numText(el, minDigits) {
        const own = [...el.childNodes].filter(n => n.nodeType === 3)
            .map(n => n.textContent).join('').trim();
        if (!re.test(own) || own.replace(/,/g, '').length < minDigits) return null;
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return null;
        if (r.left < 0 || r.left > vw || r.top < 0 || r.top > 200) return null;
        return own;
    }
    for (const el of scope.querySelectorAll('[class*="gemAmount"], [class*="GemReceived"]')) {
        const t = numText(el, 1);
        if (t) return t;
    }
    for (const el of scope.querySelectorAll('*')) {
        if (shard && shard.contains(el)) continue;
        const t = numText(el, 2);
        if (t) return t;
    }
    return null;
}'''

def readAccountBalance(page):
    '''
    Return the account gem balance as an int, or None if it can't be read.

    Defensive like isClaimable/isLoggedOut: any miss returns None rather than
    raising, so a transient hiccup never breaks the watch loop.
    '''
    scope = config.ACCOUNT_BALANCE_SCOPE
    if not scope:
        return None
    try:
        text = page.evaluate(_BALANCE_JS, {'scope': scope, 'shard': config.SHARD_AMOUNT_SELECTOR})
    except Exception:
        return None
    if not text:
        return None
    digits = ''.join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else None

def writeStatus(balance, sessionGathered) -> None:
    '''
    Atomically publish watcher stats for the control GUI to read.

    Written via a temp file + os.replace so the GUI (control.py) never reads a
    half-written file. balance may be None when the balance can't be read yet.
    '''
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        'balance': balance,
        'sessionGathered': sessionGathered,
        'updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    tmp = config.STATUS_FILE.with_suffix('.json.tmp')
    try:
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(payload, fh)
        os.replace(tmp, config.STATUS_FILE)
    except Exception:
        pass

# Discovery aid for pinning config.ACCOUNT_BALANCE_SELECTOR. Collects every
# ON-SCREEN top-nav element whose OWN text is a multi-digit gem-style number
# (e.g. "1,033") -- own text only, and length >= 2 to skip the animated odometer
# columns and single-digit counters that otherwise flood the dump. For each it
# reports the text, position, whether a diamond icon sits nearby, and the chain
# of ancestor element ids: boxed.gg gives these stable ids (e.g. a sibling of
# #top-nav-bar-shard-amount), so the tightest ancestor id that wraps only the
# balance is the robust selector to paste into config.
_PROBE_BALANCE_JS = r'''() => {
    const re = /^\d{1,3}(,\d{3})*$/;
    const vw = window.innerWidth;
    const out = [];
    for (const el of document.querySelectorAll('*')) {
        const own = [...el.childNodes].filter(n => n.nodeType === 3)
            .map(n => n.textContent).join('').trim();
        if (!re.test(own) || own.length < 2) continue;       // skip lone-digit odometer/counters
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        if (r.left < 0 || r.left > vw || r.top < 0 || r.top > 200) continue;  // on-screen top nav
        const ids = [];
        for (let anc = el, i = 0; anc && i < 10; anc = anc.parentElement, i++) {
            if (anc.id) ids.push(anc.id);
        }
        const scope = el.parentElement || el;
        out.push({
            text: own, x: Math.round(r.left), y: Math.round(r.top),
            ids, hasIcon: !!scope.querySelector('svg, img'),
        });
    }
    return out;
}'''

def probeBalances(pw, headless: bool, offscreen: bool) -> None:
    '''Open one session, dump every on-screen balance-looking element, then close.'''
    opts = config.launchOptions(headless=headless)
    if offscreen:
        opts['args'] = opts.get('args', []) + [config.WINDOW_OFFSCREEN_ARG]
    context = pw.chromium.launch_persistent_context(**opts)
    config.applyStealth(context)
    page = context.pages[0] if context.pages else context.new_page()
    try:
        page.goto(config.BOXED_URL, wait_until='domcontentloaded', timeout=45000)
        page.wait_for_timeout(config.PAGE_SETTLE_SECONDS * 1000)
        candidates = page.evaluate(_PROBE_BALANCE_JS)
        if not candidates:
            log('probe: no balance-looking elements found on screen')
        for c in candidates:
            ids = ', '.join(c['ids']) if c['ids'] else '(none)'
            log(f"probe: text={c['text']!r} pos=({c['x']},{c['y']}) "
                f"icon={c['hasIcon']} ancestorIds=[{ids}]")
        log('probe: the account balance is your real gem total (top nav, has a '
            'comma, NOT the drop pool). Set config.ACCOUNT_BALANCE_SCOPE to the '
            'tightest ancestor id that contains it but not the other numbers '
            '(currently #top-nav--desktop); readAccountBalance finds the number '
            'within that scope.')
    finally:
        try:
            context.close()
        except Exception:
            pass

def claimNow(page) -> bool:
    '''
    Click the claim button after a randomised delay. Returns True on a click.

    The delay (config.CLICK_DELAY_RANGE) keeps the action human-like; the live
    window is far longer than the delay, so we stay well inside it.
    '''
    low, high = config.CLICK_DELAY_RANGE
    delay = random.uniform(low, high)
    log(f'Drop is LIVE: claiming in {delay:.1f}s')
    time.sleep(delay)
    # The live window can be short; if it closed during the delay, skip quietly.
    if not isClaimable(page):
        log('Drop window closed during delay: skipping')
        return False
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
    # Success shows as the claim button disappearing (or disabling). Gems aren't
    # awarded yet (that happens when the drop resolves); the balance logged here
    # is just the baseline the award-detection in watchSession measures against.
    time.sleep(1.0)
    joined = not isClaimable(page)
    if joined:
        bal = readAccountBalance(page)
        log(f'Claimed: joined the drop (balance: {bal if bal is not None else "?"})')
    else:
        log('Clicked, but button still present (claim unconfirmed)')
    return joined

def watchSession(pw, headless: bool, offscreen: bool, observe: bool,
                 deadline: float, stats: dict) -> str:
    '''
    Open one browser session and watch until the deadline or a fatal error.

    stats is a mutable accumulator shared across sessions for one watcher run;
    stats['gathered'] holds gems gathered this session (see syncBalance below).

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
        # Baseline for award detection: first read sets the reference without
        # logging a delta. Gems land when a drop resolves (seconds to minutes
        # after the click), so we detect awards by watching this rise, not by
        # reading right after claiming.
        lastBalance = readAccountBalance(page)
        writeStatus(lastBalance, stats['gathered'])

        def syncBalance() -> None:
            '''Read the balance; log + accumulate any rise; refresh the status file.'''
            nonlocal lastBalance
            bal = readAccountBalance(page)
            if bal is not None:
                if lastBalance is not None and bal > lastBalance:
                    delta = bal - lastBalance
                    stats['gathered'] += delta
                    # A manual refill purchase would also register here; acceptable
                    # for this log's purpose (it just tracks balance increases).
                    log(f'Gems awarded: +{delta} (balance: {bal})')
                lastBalance = bal   # advance on rise, decrease (spend), or no change
            writeStatus(lastBalance, stats['gathered'])

        while time.time() < deadline:
            try:
                syncBalance()
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
                            log('SESSION EXPIRED: re-run login.py to refresh login')
                    else:
                        loggedOutStreak = 0
                # Periodic reload to shed memory and keep clearance fresh.
                if time.time() > nextReload:
                    page.goto(config.BOXED_URL, wait_until='domcontentloaded', timeout=45000)
                    page.wait_for_timeout(config.PAGE_SETTLE_SECONDS * 1000)
                    nextReload = time.time() + config.WATCH_RELOAD_EVERY_MINUTES * 60
                    # The balance element is rebuilt by the reload; re-baseline
                    # to the same server-side value so the refresh logs no award.
                    rebaselined = readAccountBalance(page)
                    if rebaselined is not None:
                        lastBalance = rebaselined
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
    parser.add_argument('--probe-balance', dest='probeBalance', action='store_true',
                        help='Dump candidate balance elements (to pin the selector) and exit.')
    return parser.parse_args()

def main() -> int:
    args = parseArgs()
    if not config.PROFILE_DIR.exists():
        log('No browser profile found: run login.py first.')
        return 2
    if args.probeBalance:
        with sync_playwright() as pw:
            probeBalances(pw, headless=config.WATCH_HEADLESS, offscreen=not args.visible)
        return 0
    deadline = time.time() + args.minutes * 60 if args.minutes else float('inf')
    log(f'watcher starting (poll {config.POLL_INTERVAL_SECONDS}s, '
        f'delay {config.CLICK_DELAY_RANGE[0]}-{config.CLICK_DELAY_RANGE[1]}s)')
    # Gems gathered this watcher run; survives session relaunches/reloads below.
    stats = {'gathered': 0}
    with sync_playwright() as pw:
        while time.time() < deadline:
            reason = watchSession(pw, headless=config.WATCH_HEADLESS,
                                  offscreen=not args.visible, observe=args.observe,
                                  deadline=deadline, stats=stats)
            if reason == 'deadline':
                break
            time.sleep(5)   # brief backoff before relaunching a dead session
    log('watcher stopped')
    return 0

if __name__ == '__main__':
    sys.exit(main())
