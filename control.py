'''
Boxed Watcher control panel: a tiny always-on-top GUI on/off switch.

The gem-drop watcher runs as the `BoxedGemWatcher` Scheduled Task and is
otherwise invisible (windowless `pythonw.exe`). This panel lets you flip it off
when you want the CPU/RAM and Chrome back for other work, then on again later,
without touching Task Scheduler or hunting for the process.

OFF: ends the task, disables it (so it does not relaunch at the next logon or
     via the restart policy), and force-stops any lingering watcher + the
     off-screen Chrome it spawned, so nothing is left consuming resources.
ON:  re-enables the task and starts it immediately.

Usage:
    pythonw control.py        # launch the GUI (no console window)
    python  control.py --status   # print state and exit (no GUI)
    python  control.py --on / --off

Sean Bowman [06/2026]
'''

import os
import sys
import subprocess
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import TASK_NAME

# Hide every child console window (schtasks/tasklist/powershell) so nothing flashes.
_NO_WINDOW = 0x08000000  # subprocess.CREATE_NO_WINDOW

# PowerShell snippet that force-stops the watcher and its off-screen Chrome.
_KILL_STRAGGLERS = (
    "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | "
    "Where-Object CommandLine -like '*watch.py*' | "
    "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }; "
    "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
    "Where-Object CommandLine -like '*autoClicker*browserProfile*' | "
    "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
)


def _run(args: list[str]) -> subprocess.CompletedProcess:
    '''Run a command with no console window, capturing text output.'''
    return subprocess.run(
        args, capture_output=True, text=True, creationflags=_NO_WINDOW
    )


def getState() -> str:
    '''
    Return the watcher state derived from the Scheduled Task:
        'running'   : task is enabled and the watcher is executing
        'stopped'   : task is enabled but not currently running
        'disabled'  : task exists but is disabled (our OFF state)
        'missing'   : task is not registered (run setupTask.ps1)
    '''
    result = _run(['schtasks', '/query', '/tn', TASK_NAME, '/fo', 'csv', '/nh'])
    if result.returncode != 0:
        return 'missing'
    # CSV row: "TaskName","Next Run Time","Status"
    fields = [f.strip('"') for f in result.stdout.strip().splitlines()[-1].split('","')]
    status = fields[-1].strip().lower() if fields else ''
    if status == 'running':
        return 'running'
    if status == 'disabled':
        return 'disabled'
    return 'stopped'


def turnOn() -> None:
    '''Enable and immediately start the watcher task.'''
    _run(['schtasks', '/change', '/tn', TASK_NAME, '/enable'])
    _run(['schtasks', '/run', '/tn', TASK_NAME])


def turnOff() -> None:
    '''End and disable the task, then force-stop any stragglers.'''
    _run(['schtasks', '/end', '/tn', TASK_NAME])
    _run(['schtasks', '/change', '/tn', TASK_NAME, '/disable'])
    _run(['powershell', '-NoProfile', '-Command', _KILL_STRAGGLERS])


# -- GUI ------------------------------------------------------------------- #

# state -> (dot color, status label, on/off-ness)
_VISUALS = {
    'running':  ('#34d399', 'RUNNING', True),
    'stopped':  ('#fbbf24', 'STOPPED', False),
    'disabled': ('#f87171', 'OFF', False),
    'missing':  ('#64748b', 'NOT INSTALLED', None),
}

_BG = '#1a1e2e'
_SURFACE = '#252b3b'
_TEXT = '#e2e8f0'
_MUTED = '#94a3b8'
_ACCENT = '#5eadb5'


def launchGui() -> None:
    '''Build and run the always-on-top control window.'''
    import tkinter as tk

    root = tk.Tk()
    root.title('Boxed Watcher')
    root.configure(bg=_BG)
    root.geometry('300x190')
    root.resizable(False, False)
    root.attributes('-topmost', True)

    header = tk.Label(root, text='Boxed Gem Watcher', bg=_BG, fg=_TEXT,
                      font=('Segoe UI', 12, 'bold'))
    header.pack(pady=(16, 4))

    statusFrame = tk.Frame(root, bg=_BG)
    statusFrame.pack(pady=2)
    dot = tk.Canvas(statusFrame, width=16, height=16, bg=_BG, highlightthickness=0)
    dotId = dot.create_oval(2, 2, 14, 14, fill=_MUTED, outline='')
    dot.pack(side='left', padx=(0, 8))
    statusLabel = tk.Label(statusFrame, text='checking...', bg=_BG, fg=_TEXT,
                           font=('Segoe UI', 11))
    statusLabel.pack(side='left')

    toggle = tk.Button(root, text='...', width=18, height=2, bd=0,
                       bg=_SURFACE, fg=_TEXT, activebackground=_ACCENT,
                       activeforeground='white', font=('Segoe UI', 11, 'bold'),
                       cursor='hand2')
    toggle.pack(pady=12)

    note = tk.Label(root, text='', bg=_BG, fg=_MUTED, font=('Segoe UI', 8))
    note.pack()

    busy = {'flag': False}

    def render(state: str) -> None:
        color, text, isOn = _VISUALS[state]
        dot.itemconfig(dotId, fill=color)
        statusLabel.config(text=text)
        if state == 'missing':
            toggle.config(text='task not installed', state='disabled')
            note.config(text='Run setupTask.ps1 to register the watcher.')
        elif isOn:
            toggle.config(text='Turn OFF', state='normal', fg='#fca5a5')
            note.config(text='Watcher is claiming drops in the background.')
        else:
            toggle.config(text='Turn ON', state='normal', fg='#86efac')
            note.config(text='Watcher is stopped: no CPU/Chrome in use.')

    def refresh() -> None:
        if not busy['flag']:
            render(getState())
        root.after(3000, refresh)

    def onToggle() -> None:
        if busy['flag']:
            return
        currentlyOn = _VISUALS[getState()][2]
        busy['flag'] = True
        toggle.config(text='working...', state='disabled')
        statusLabel.config(text='working...')

        def work() -> None:
            try:
                turnOff() if currentlyOn else turnOn()
            finally:
                busy['flag'] = False
                root.after(0, lambda: render(getState()))

        threading.Thread(target=work, daemon=True).start()

    toggle.config(command=onToggle)
    render(getState())
    refresh()
    root.mainloop()


def main() -> None:
    args = sys.argv[1:]
    if '--status' in args:
        print(getState())
    elif '--on' in args:
        turnOn()
        print(getState())
    elif '--off' in args:
        turnOff()
        print(getState())
    else:
        launchGui()


if __name__ == '__main__':
    main()
