# Source-control benchmark

Compare VS Code, LVCE Editor and Atom after deleting the root `node_modules` directory of the VS Code **1.139.0** source checkout with dependencies installed. Results are published to [GitHub Pages](https://levivilet.github.io/source-control-benchmark/) only after every trial succeeds.

## Scenario and metric

1. Clone the exact revision in `config/fixture.json`, use its Node version, and run `nice npm ci` with lifecycle scripts enabled. Python, compiler, native library and desktop prerequisites are installed by the workflow.
2. Preserve the installed root dependency tree. Before every trial restore it, verify clean Git status and launch the editor with a fresh Chromium and application profile. Nested workspace dependencies remain installed. The fixture version and editor versions are independent; editor binaries and SHA-256 digests are pinned in `config/editors.lock.json`.
3. Open source control. Require the visible changes view to be empty, at least one successful editor-origin Git status, no active Git command, and three seconds without Git trace activity.
4. Delete root `node_modules`, timing deletion separately. Wait for another successful automatic Git status, a clean visible changes view, no active Git commands and three seconds without Git trace activity. Do not manually refresh, create a marker file, modify ignore rules or inject a synthetic source-control change.
5. Save total elapsed time (from deletion start), deletion duration, remaining settling time, UI observations, screenshots, Git Trace2 events, versions, fixture sizes and host information. Shut down the editor before deleting its profile.

The total is an **observable settling bound**, including deletion and the quiet window, sampled every 250 ms. It is not a measurement of all internal queues or CPU idle. Ignored files leave the visible change count at zero, so that alone is insufficient. An editor that never emits the required refresh evidence is inconclusive and fails the run; it is never represented as zero milliseconds. Timeouts (120 seconds), crashes and Git status errors also fail. Git traces are inherited only by the editor, so the harness's independent clean-status checks cannot satisfy the completion gate.

GitHub Actions runs all three editors in separate Ubuntu 26.04 jobs, with one trial per PR and three per editor on main. These are separate runner hosts: compare with that limitation in mind. The report displays individual trials and medians, and includes raw JSON and evidence. Failed or incomplete inventories cannot replace the published report.

## Run on Linux

Install the packages listed in `.github/workflows/benchmark.yml`, Node 24.18.0, and Python 3.12 or newer. Use a fresh checkout/run directory with enough space for the VS Code dependency installation and a second copy of root `node_modules`.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/install.py --editors vscode
.venv/bin/python scripts/prepare.py
xvfb-run -a .venv/bin/python scripts/benchmark.py --editor vscode --repeats 3
python3 -m unittest discover -s tests
```

Repeat with separate fresh run directories for `lvce` and `atom`; gather each editor's `results/<editor>` into one `results` directory, then run `scripts/report.py --repeats 3 --run-url URL --commit SHA`. The generated static site is `.tmp/pages`.

No third-party repository is modified or receives a pull request. Editor installer patterns and pinned releases derive from [lvce-idle-cpu-benchmark](https://github.com/levivilet/lvce-idle-cpu-benchmark).
