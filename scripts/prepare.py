"""Prepare one disposable, dependency-installed VS Code fixture outside measurement."""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / '.tmp/fixture'


def run(*args, cwd=FIXTURE):
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


def clean():
    status = run('git', 'status', '--porcelain', '--untracked-files=all')
    if status:
        raise RuntimeError(f'Fixture must be clean: {status[:2000]}')


def main():
    lock = json.loads((ROOT / 'config/fixture.json').read_text())
    if not FIXTURE.exists():
        FIXTURE.parent.mkdir(exist_ok=True)
        subprocess.run(['git', 'clone', '--depth=1', '--branch', lock['tag'], lock['repository'], str(FIXTURE)], check=True)
    if run('git', 'rev-parse', 'HEAD') != lock['commit']:
        raise RuntimeError('Unexpected fixture revision; refusing to change an existing checkout')
    if run('node', '--version') != 'v' + lock['node']:
        raise RuntimeError('Install the fixture Node version from config/fixture.json')
    clean()
    # Lifecycle scripts are deliberately enabled: native builds and nested installs matter.
    subprocess.run(['nice', 'npm', 'ci'], cwd=FIXTURE, check=True)
    clean()
    modules = FIXTURE / 'node_modules'
    files = [p for p in modules.rglob('*') if p.is_file() and not p.is_symlink()]
    if not files:
        raise RuntimeError('No installed dependencies')
    metadata = {**lock, 'files': len(files), 'bytes': sum(p.stat().st_size for p in files),
                'npm': run('npm', '--version'), 'install': 'nice npm ci (including lifecycle scripts)',
                'deletionScope': 'root node_modules only; nested workspace installations remain'}
    (ROOT / '.tmp/fixture.json').write_text(json.dumps(metadata, indent=2))


if __name__ == '__main__':
    main()
