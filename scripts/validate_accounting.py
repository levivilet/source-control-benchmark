"""Hardware acceptance for descendants, cutoff timing and harness exclusion."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from counters import Capture


def measure(perf, mode, harness=False):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        if 'SUDO_UID' in os.environ:
            os.chown(root, int(os.environ['SUDO_UID']), int(os.environ['SUDO_GID']))
        try:
            with Capture(perf, root) as capture:
                (root / 'ready').unlink(missing_ok=True)
                with (root / 'stdout').open('w') as stdout, (root / 'stderr').open('w') as stderr:
                    child = capture.launch([
                        str(Path('.tmp/instruction-workload').resolve()), mode,
                        str(root / 'ready'), str(root / 'go'), str(root / 'done'),
                        str(root / 'release'), '200000000'], os.environ.copy(), stdout, stderr)
                wait_for(root / 'ready')
                capture.start()
                (root / 'go').touch()
                harness_process = None
                if harness:
                    harness_process = subprocess.Popen([sys.executable, '-c', 'sum(i*i for i in range(20000000))'])
                wait_for(root / 'done')
                if harness_process:
                    harness_process.wait(timeout=20)
                capture.cutoff()
                (root / 'release').touch()
                child.wait(timeout=20)
                return capture.finish()
        except BaseException:
            log = root / 'perf.log'
            if log.exists():
                Path('results/accounting-failure.log').write_text(log.read_text())
            raise


def wait_for(path):
    deadline = time.monotonic() + 10
    while not path.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError(f'workload readiness timeout: {path.name}')
        time.sleep(.005)


def main():
    Path('results').mkdir(exist_ok=True)
    Path('.tmp').mkdir(exist_ok=True)
    subprocess.run(['cc', '-O2', 'tests/workload.c', '-o', '.tmp/instruction-workload'], check=True)
    results = {'direct': measure(sys.argv[1], 'direct'),
               'descendant': measure(sys.argv[1], 'descendant'),
               'harness': measure(sys.argv[1], 'direct', harness=True),
               'postCutoff': measure(sys.argv[1], 'direct')}
    baseline = results['direct']['instructions']
    for name, result in results.items():
        result['ratioToDirect'] = result['instructions'] / baseline
        if not .9 < result['ratioToDirect'] < 1.1:
            Path('results/accounting.json').write_text(json.dumps(results, indent=2) + '\n')
            raise SystemExit(f'{name}: accounting mismatch {result["ratioToDirect"]}')
    Path('results/accounting.json').write_text(json.dumps(results, indent=2) + '\n')
    print('Descendant inclusion, cutoff correctness and harness exclusion validated')


if __name__ == '__main__':
    main()
