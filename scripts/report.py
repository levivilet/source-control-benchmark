"""Validate the complete inventory before publishing measured charts."""
import argparse
import html
import json
import math
from pathlib import Path
import shutil
import statistics
from protocol import CPU_PERCENT_LIMIT, QUIET_SECONDS

ROOT = Path(__file__).resolve().parent.parent


def validate(results, repeats, editors, fixture):
    expected = {(e['id'], n) for e in editors for n in range(1, repeats + 1)}
    observed = set()
    for result in results:
        identity = (result['editor']['id'], result['trial'])
        if identity in observed or identity not in expected:
            raise ValueError('Duplicate or unexpected result')
        observed.add(identity)
        if result['status'] != 'ok' or not result.get('deleted'):
            raise ValueError('Unsuccessful trial')
        if result['editor'] not in editors or result['fixture']['commit'] != fixture['commit']:
            raise ValueError('Incorrect provenance')
        if result['finalStatuses'] < result['baselineStatuses'] or result['baselineStatuses'] < 1:
            raise ValueError('Missing baseline status evidence')
        if result['refreshObserved'] != (result['finalStatuses'] > result['baselineStatuses']):
            raise ValueError('Inconsistent refresh evidence')
        samples = result.get('cpuEvidence', [])
        if len(samples) < 2 or samples[-1]['seconds'] - samples[0]['seconds'] < QUIET_SECONDS:
            raise ValueError('Missing CPU quiet-window evidence')
        for i, sample in enumerate(samples):
            cpu = sample.get('cpuPercent')
            if cpu is None or not math.isfinite(cpu) or not 0 <= cpu <= CPU_PERCENT_LIMIT or not sample['ready'] or sample['activeGit']:
                raise ValueError('Editor was not observably idle')
            if i and not 0 < sample['seconds'] - samples[i-1]['seconds'] <= 1:
                raise ValueError('Discontinuous CPU evidence')
            if sample['traceLines'] != samples[0]['traceLines']:
                raise ValueError('Git activity inside quiet window')
        for key in ['totalSeconds', 'deletionSeconds', 'afterDeletionSeconds']:
            value = result[key]
            if not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
                raise ValueError('Invalid duration')
        if not math.isclose(result['totalSeconds'], result['deletionSeconds'] + result['afterDeletionSeconds'], abs_tol=.001):
            raise ValueError('Inconsistent timing')
    if observed != expected:
        raise ValueError('Incomplete editor/trial inventory')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--run-url', required=True)
    parser.add_argument('--commit', required=True)
    args = parser.parse_args()
    editors = json.loads((ROOT / 'config/editors.lock.json').read_text())
    fixture = json.loads((ROOT / 'config/fixture.json').read_text())
    files = sorted((ROOT / 'results').rglob('result.json'))
    results = [json.loads(p.read_text()) for p in files]
    validate(results, args.repeats, editors, fixture)
    output = ROOT / '.tmp/pages'
    output.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / 'results', output / 'evidence', dirs_exist_ok=True)
    (output / 'results.json').write_text(json.dumps({'runUrl': args.run_url, 'commit': args.commit, 'results': results}, indent=2))
    medians = {e['id']: statistics.median(r['totalSeconds'] for r in results if r['editor']['id'] == e['id']) for e in editors}
    maximum = max(medians.values()) * 1.2
    svg = ['<svg viewBox="0 0 900 440" role="img" aria-label="Median source-control settling time in seconds">']
    for tick in range(5):
        y = 350 - tick * 70
        svg.append(f'<line x1="80" y1="{y}" x2="850" y2="{y}" stroke="#ccd7e5"/><text x="65" y="{y+5}" text-anchor="end">{maximum*tick/4:.1f}</text>')
    for i, editor in enumerate(sorted(editors, key=lambda e: medians[e['id']])):
        x = 210 + i * 260
        value = medians[editor['id']]
        y = 350 - 280 * value / maximum
        svg.append(f'<line x1="{x}" x2="{x}" y1="350" y2="{y}" stroke="#1763aa"/><circle cx="{x}" cy="{y}" r="6" fill="#1763aa"/><text x="{x}" y="{y-16}" text-anchor="middle">{value:.3f} s</text><text x="{x}" y="395" text-anchor="middle">{html.escape(editor["name"])}</text>')
    svg.append('</svg>')
    rows = ''.join(f'<tr><td>{html.escape(r["editor"]["name"])}</td><td>{html.escape(r["editor"]["version"])}</td><td>{r["trial"]}</td><td>{r["deletionSeconds"]:.3f}</td><td>{r["afterDeletionSeconds"]:.3f}</td><td>{r["totalSeconds"]:.3f}</td><td>{"Observed" if r["refreshObserved"] else "Not observed"}</td></tr>' for r in results)
    page = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Source-control benchmark</title>
<style>body{{font:16px/1.6 system-ui;background:#f4f7fa;color:#142b43;margin:40px auto;padding:0 24px;max-width:1100px}}svg{{width:100%;background:white;border:1px solid #ccd7e5;border-radius:8px}}text{{font:16px system-ui;fill:#142b43}}aside{{background:#e6f0fa;padding:20px;border-radius:8px}}table{{width:100%;border-collapse:collapse;background:white}}th,td{{text-align:left;padding:10px;border-bottom:1px solid #ccd7e5}}a{{color:#1763aa}}.scroll{{overflow:auto}}</style>
<h1>Source-control benchmark</h1><p>VS Code 1.139.0 repository, installed dependencies, clean source control, then deletion of root node_modules.</p>
<p>Complete run: <a href="{html.escape(args.run_url, quote=True)}">GitHub Actions</a> · benchmark commit {html.escape(args.commit)}</p>
<aside>This measures an observable settling bound: deletion start to a clean source-control view, no Git activity and three seconds of editor process-tree CPU at or below 5% of one logical CPU. It includes deletion and the quiet window. Cgroup v2 accounts for the editor and all descendants, including short-lived Git processes. This operational idle threshold does not prove every internal queue is empty. Lower is faster under this protocol. Missing CPU evidence, crashes and timeouts fail publication. Editors that ignore this directory may perform no Git refresh; that is explicitly reported and is never assigned a zero duration.</aside>
<p>All three editors completed {args.repeats} trials each. Each trial restores the same installed dependency tree and uses a fresh isolated profile. Fixture revision: {fixture['commit']}.</p>
<h2>Median settling time (seconds)</h2>{''.join(svg)}
<h2>Individual trials</h2><div class="scroll"><table><thead><tr><th>Editor</th><th>Version</th><th>Trial</th><th>Deletion (s)</th><th>After deletion (s)</th><th>Total (s)</th><th>Automatic Git refresh</th></tr></thead><tbody>{rows}</tbody></table></div>
<p><a href="results.json">Download raw measurements and provenance</a>. Evidence includes per-trial screenshots, Git traces, UI observations and logs.</p>
<ul>{''.join(f'<li><a href="evidence/{p.relative_to(ROOT / "results").as_posix()}">{html.escape(p.relative_to(ROOT / "results").as_posix())}</a></li>' for p in files)}</ul>
</html>'''
    (output / 'index.html').write_text(page)


if __name__ == '__main__':
    main()
