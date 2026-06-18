'''
One-shot gem-drop claimer for boxed.gg.

This is the script Windows Task Scheduler fires every hour. It loads the
persistent browser profile created by login.py, navigates to boxed.gg already
authenticated, claims whatever gem drops are currently available, records the
outcome, and exits. It is idempotent: running it when nothing is claimable is a
harmless no-op.

Exit codes:
    0  success (claimed something, or nothing was claimable)
    2  session expired / not logged in (re-run login.py)
    3  unexpected error (a screenshot + HTML dump is written to logs/)

Usage:
    python claim.py                 # headless, as scheduled
    python claim.py --headed        # visible window, for debugging / discovery
    python claim.py --headed --keep-open  # stay open after claiming, to inspect the DOM
'''

import argparse
import sys
from datetime import datetime

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

import config


def timestamp() -> str:
    '''Local timestamp for log lines and filenames.'''
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def logResult(message: str) -> None:
    '''
    Append one timestamped line to the rolling run log and echo it to stdout.

    Task Scheduler discards stdout, so the file is the durable record of whether
    the hourly run actually fired and what it did.
    '''
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = f'[{timestamp()}] {message}'
    print(line)
    with open(config.LOG_DIR / 'claim.log', 'a', encoding='utf-8') as handle:
        handle.write(line + '\n')


def dumpFailure(page, label: str) -> None:
    '''
    Save a screenshot + full HTML of the current page for offline debugging.

    Called on the unexpected-error path and whenever selector tuning is needed —
    the saved DOM is what we mine to populate config.CLAIM_SELECTORS.
    '''
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    shotPath = config.LOG_DIR / f'{label}_{stamp}.png'
    htmlPath = config.LOG_DIR / f'{label}_{stamp}.html'
    try:
        page.screenshot(path=str(shotPath), full_page=True)
        htmlPath.write_text(page.content(), encoding='utf-8')
        logResult(f'Saved debug artifacts: {shotPath.name}, {htmlPath.name}')
    except Exception as exc:  # best-effort; never mask the original failure
        logResult(f'Could not save debug artifacts: {exc!r}')


def claimDrops(page) -> int:
    '''
    Click every visible, enabled gem-drop control matched by CLAIM_SELECTORS.

    Returns the number of claim controls clicked. Each selector is tried in turn;
    matches that are hidden or disabled are skipped so an already-claimed pool
    does not cause spurious clicks.
    '''
    clicked = 0
    for selector in config.CLAIM_SELECTORS:
        locator = page.locator(selector)
        count = locator.count()
        for index in range(count):
            element = locator.nth(index)
            try:
                if not element.is_visible() or not element.is_enabled():
                    continue
                element.click(timeout=4000)
                clicked += 1
                logResult(f'Clicked claim control: {selector} [#{index}]')
                # Let any post-click animation / network claim settle before the
                # next click so the site registers each claim.
                page.wait_for_timeout(1500)
            except PlaywrightTimeoutError:
                # Element matched but was not actually clickable — skip it.
                continue
            except Exception as exc:
                logResult(f'Click failed on {selector} [#{index}]: {exc!r}')
                continue
    return clicked


def runClaim(headed: bool, keepOpen: bool) -> int:
    '''Drive a single claim pass. Returns the process exit code.'''
    if not config.PROFILE_DIR.exists():
        logResult('No browser profile found — run login.py first.')
        return 2

    headless = config.HEADLESS and not headed
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(config.PROFILE_DIR),
            headless=headless,
            # Real desktop UA clears CloudFront's headless 403 (see config.py).
            user_agent=config.USER_AGENT,
            args=config.BROWSER_ARGS,
            viewport={'width': 1280, 'height': 900},
        )
        page = context.pages[0] if context.pages else context.new_page()

        try:
            page.goto(config.BOXED_URL, wait_until='domcontentloaded', timeout=45000)
            # boxed.gg hydrates its claim widgets client-side after load.
            page.wait_for_timeout(config.PAGE_SETTLE_SECONDS * 1000)

            # Fail fast and loud if the saved session has expired, rather than
            # silently clicking nothing for weeks.
            if page.locator(config.LOGGED_OUT_SELECTOR).first.is_visible():
                logResult('Appears logged out — session expired. Re-run login.py.')
                dumpFailure(page, 'logged_out')
                return 2

            clicked = claimDrops(page)
            if clicked:
                logResult(f'Run complete — claimed {clicked} drop(s).')
            else:
                # Not necessarily an error: the pool may already be claimed.
                logResult('Run complete — nothing claimable this pass.')
                dumpFailure(page, 'nothing_claimed')

            if keepOpen:
                print('--keep-open set; press Enter to close the browser...')
                input()
            return 0

        except Exception as exc:
            logResult(f'Unexpected error: {exc!r}')
            dumpFailure(page, 'error')
            return 3
        finally:
            context.close()


def parseArgs() -> argparse.Namespace:
    '''Parse CLI flags for the headed/keep-open debugging modes.'''
    parser = argparse.ArgumentParser(description='Claim boxed.gg gem drops (one shot).')
    parser.add_argument('--headed', action='store_true',
                        help='Run with a visible browser window (debugging/discovery).')
    parser.add_argument('--keep-open', action='store_true',
                        help='Keep the browser open after the pass until Enter is pressed.')
    return parser.parse_args()


if __name__ == '__main__':
    args = parseArgs()
    sys.exit(runClaim(headed=args.headed, keepOpen=args.keep_open))
