'''
One-time interactive login for the boxed.gg gem-drop claimer.

Run this once (and again only when the session expires). It opens a real,
visible Chromium window using a persistent profile directory. You log in by
hand — email + password, plus any captcha or 2FA the site throws up. When you
close the window, Chromium has already written the resulting cookies and
localStorage into PROFILE_DIR, so the headless claim.py can reuse the session
without ever touching your password.

Usage:
    python login.py
'''

import sys

from playwright.sync_api import sync_playwright

import config

def runLogin() -> int:
    '''
    Launch a headed persistent-context browser and wait for the user to log in.

    Returns a process exit code (0 on a clean close).
    '''
    config.PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        # A persistent context (vs. a throwaway browser) is what makes the login
        # survive between runs: everything is keyed to the on-disk profile dir.
        # launchOptions() drives real Chrome with automation flags stripped so
        # Cloudflare's human-verification step can be passed manually.
        context = pw.chromium.launch_persistent_context(**config.launchOptions(headless=False))
        config.applyStealth(context)

        page = context.pages[0] if context.pages else context.new_page()
        page.goto(config.BOXED_URL, wait_until='domcontentloaded')

        print('-' * 70)
        print('A browser window has opened on boxed.gg.')
        print('Log in with your email + password (and any captcha / 2FA).')
        print('When you are fully logged in, just CLOSE the browser window.')
        print('Your session will be saved automatically.')
        print('-' * 70)

        # Block until the user closes the window. We wait on the context's close
        # event rather than page.pause() so there is no inspector overlay to
        # interfere with the real login flow.
        closedFlag = {'done': False}
        context.on('close', lambda: closedFlag.__setitem__('done', True))
        try:
            # page.wait_for_event('close') resolves when the user closes the tab/window.
            page.wait_for_event('close', timeout=0)
        except Exception:
            # Context torn down out from under the page — that is the expected
            # path when the whole window is closed.
            pass

    print('Session saved to', config.PROFILE_DIR)
    return 0

if __name__ == '__main__':
    sys.exit(runLogin())
