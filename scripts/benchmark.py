"""Measure natural source-control refresh after deleting ignored dependencies."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import socket
import subprocess
import time

from cdp import Page
from prepare import FIXTURE, ROOT, clean
from protocol import Completion, trace_state, QUIET_SECONDS, TIMEOUT_SECONDS


STATE = {
    'vscode': """(() => {
      const view = document.querySelector('.scm-view');
      return !!view && !!view.offsetHeight && !!view.querySelector('.scm-input') &&
        !view.querySelector('.resource') && !view.querySelector('.monaco-progress-container.active');
    })()""",
    'lvce': """(() => {
      const view = document.querySelector('.SourceControl');
      return !!view && !!view.offsetHeight && !!view.querySelector('textarea') &&
        !view.querySelector('.TreeItem') && view.getAttribute('aria-busy') !== 'true';
    })()""",
    'atom': """(() => {
      const view = document.querySelector('.github-StagingView');
      return !!view && !!view.offsetHeight && !view.querySelector('.github-FilePatchListView-item') &&
        !document.querySelector('.github-Git.is-loading');
    })()""",
}


def stop(process):
    if process is None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
    except ProcessLookupError:
        pass
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)


def trial(editor, number, snapshot):
    output = ROOT / 'results' / editor['id'] / str(number)
    output.mkdir(parents=True)
    profile = ROOT / '.tmp' / f"profile-{editor['id']}-{number}"
    profile.mkdir()
    trace = output / 'git.jsonl'
    env = {**os.environ, 'GIT_TRACE2_EVENT': str(trace), 'LIBGL_ALWAYS_SOFTWARE': '1',
           'ATOM_HOME': str(profile / 'atom'), 'ELECTRON_OZONE_PLATFORM_HINT': 'x11'}
    for name in ['CONFIG', 'CACHE', 'DATA', 'STATE']:
        directory = profile / name.lower()
        directory.mkdir()
        env[f'XDG_{name}_HOME'] = str(directory)
    settings = profile / 'chromium' / 'User'
    settings.mkdir(parents=True)
    (settings / 'settings.json').write_text(json.dumps({
        'workbench.startupEditor': 'none', 'security.workspace.trust.enabled': False,
        'git.autofetch': False, 'extensions.autoUpdate': False, 'update.mode': 'none',
    }))
    with socket.socket() as port_socket:
        port_socket.bind(('127.0.0.1', 0))
        port = port_socket.getsockname()[1]
    binary = ROOT / '.tmp/apps' / editor['id'] / editor['binary']
    command = [str(binary), '--no-sandbox', '--disable-gpu', f'--remote-debugging-port={port}',
               '--user-data-dir=' + str(profile / 'chromium')]
    if editor['id'] == 'vscode':
        command += ['--disable-extensions', '--skip-welcome', '--skip-release-notes', '--disable-workspace-trust', '--new-window']
    if editor['id'] == 'atom':
        command += ['--new-window', '--foreground']
    command.append(str(FIXTURE))
    modules = FIXTURE / 'node_modules'
    if modules.exists():
        shutil.rmtree(modules)
    shutil.copytree(snapshot, modules, symlinks=True)
    clean()
    result = {'editor': editor, 'trial': number, 'status': 'failed', 'host': {
        'platform': platform.platform(), 'cpuCount': os.cpu_count(),
        'cpu': next((line.split(':', 1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines()
                     if line.startswith('model name')), 'unknown'),
    }, 'fixture': json.loads((ROOT / '.tmp/fixture.json').read_text()),
        'protocol': {'quietSeconds': QUIET_SECONDS, 'timeoutSeconds': TIMEOUT_SECONDS,
                     'pollSeconds': .25, 'completion': 'successful post-deletion Git status + clean SCM UI + no Git trace activity for quiet window'}}
    process = page = None
    observations = []
    try:
        with (output / 'editor.log').open('w') as log:
            process = subprocess.Popen(command, env=env, stdout=log, stderr=log, start_new_session=True)
        page = Page(port)
        deadline = time.monotonic() + 60
        while not page.evaluate("document.readyState === 'complete'"):
            if time.monotonic() >= deadline:
                raise TimeoutError('Editor page not ready')
            time.sleep(.25)
        if editor['id'] == 'atom':
            page.evaluate("atom.commands.dispatch(atom.views.getView(atom.workspace), 'github:toggle-git-tab')")
        else:
            page.key('g', 'KeyG', 10)  # Control + Shift
        initial = Completion(0, time.monotonic())
        while True:
            active, statuses, errors, count = trace_state(trace)
            if initial.observe(time.monotonic(), alive=process.poll() is None,
                               ready=page.evaluate(STATE[editor['id']]), active=active,
                               statuses=statuses, errors=errors, count=count):
                break
            time.sleep(.25)
        page.screenshot(output / 'before.png')
        result['baselineStatuses'] = statuses
        # The harness's own git validation never receives GIT_TRACE2_EVENT.
        clean()
        started = time.monotonic()
        wall_started = time.time()
        completion = Completion(0, started)
        shutil.rmtree(modules)
        deleted = time.monotonic()
        result['deletionSeconds'] = deleted - started
        if modules.exists():
            raise RuntimeError('node_modules deletion did not finish')
        result['deleted'] = True
        while True:
            now = time.monotonic()
            active, statuses, errors, count = trace_state(trace, since=wall_started)
            ready = page.evaluate(STATE[editor['id']])
            observations.append({'seconds': now - started, 'ready': ready, 'activeGit': len(active),
                                 'statuses': statuses, 'traceLines': count})
            if completion.observe(now, alive=process.poll() is None, ready=ready, active=active,
                                  statuses=statuses, errors=errors, count=count):
                break
            time.sleep(.25)
        clean()
        page.screenshot(output / 'after.png')
        result.update(status='ok', totalSeconds=now - started, afterDeletionSeconds=now - deleted,
                      finalStatuses=result['baselineStatuses'] + statuses)
    except Exception as error:
        result['error'] = f'{type(error).__name__}: {error}'
        if page:
            try:
                page.screenshot(output / 'failure.png')
                (output / 'dom.html').write_text(page.evaluate('document.documentElement.outerHTML'))
            except Exception:
                pass
    finally:
        if page:
            page.close()
        stop(process)
        (output / 'observations.json').write_text(json.dumps(observations, indent=2))
        (output / 'result.json').write_text(json.dumps(result, indent=2))
        shutil.rmtree(profile)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--editor', choices=list(STATE), required=True)
    parser.add_argument('--repeats', type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('repeats must be positive')
    editor = next(e for e in json.loads((ROOT / 'config/editors.lock.json').read_text()) if e['id'] == args.editor)
    snapshot = ROOT / '.tmp/dependencies'
    if snapshot.exists():
        raise RuntimeError('Use a fresh run directory; dependency snapshot already exists')
    shutil.copytree(FIXTURE / 'node_modules', snapshot, symlinks=True)
    results = [trial(editor, number, snapshot) for number in range(1, args.repeats + 1)]
    for result in results:
        print(result['editor']['name'], result['trial'], result['status'], result.get('error', result.get('totalSeconds')))
    if any(r['status'] != 'ok' for r in results):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
