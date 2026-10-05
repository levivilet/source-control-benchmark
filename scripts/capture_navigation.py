"""Patch only the disposable pinned LVCE bundle for navigation diagnostics."""
from pathlib import Path

from install import ROOT


CAPTURE = """
globalThis.___receivedMessages = [];
const benchmarkCapture = (direction, message) => {
  let payload;
  try {
    const seen = new WeakSet();
    payload = JSON.parse(JSON.stringify(message, (key, value) => {
      if (/token|password|authorization|secret|clipboard/i.test(key)) return '[redacted]';
      if (typeof value === 'bigint') return String(value);
      if (typeof value === 'function' || typeof value === 'symbol') return String(value);
      if (value && typeof value === 'object') {
        if (seen.has(value)) return '[circular]';
        seen.add(value);
      }
      return value;
    }));
  } catch { payload = {serializationError: true}; }
  globalThis.___receivedMessages.push({
    sequence: globalThis.___receivedMessages.length,
    wallTime: Date.now(), monotonicTime: performance.now(),
    direction, type: message?.method || message?.type, payload
  });
};
"""


def main():
    bundles = list((ROOT / '.tmp/apps/lvce/usr/lib/lvce/resources/app/static').glob(
        '*/packages/renderer-process/dist/rendererProcessMain.js'))
    if len(bundles) != 1:
        raise RuntimeError(f'Expected exactly one renderer bundle, got {bundles}')
    bundle = bundles[0]
    source = bundle.read_text()
    patches = {
        'const handleMessage = event => {': CAPTURE + '''
const handleMessage = event => {
  benchmarkCapture('renderer-worker->renderer-process', event.data);''',
        '      worker.postMessage(message);': '''
      benchmarkCapture('renderer-process->renderer-worker', message);
      worker.postMessage(message);''',
        '      worker.postMessage(message, transfer);': '''
      benchmarkCapture('renderer-process->renderer-worker', message);
      worker.postMessage(message, transfer);''',
    }
    for before, after in patches.items():
        if source.count(before) != 1:
            raise RuntimeError(f'Expected one capture target: {before}')
        source = source.replace(before, after)
    bundle.write_text(source)
    print(f'Patched checksum-verified LVCE renderer: {bundle}')


if __name__ == '__main__':
    main()
