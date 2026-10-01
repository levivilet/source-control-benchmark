"""Small synchronous CDP client, also compatible with Atom's older Chromium."""
import base64
import json
import time
import urllib.request
import websocket


class Page:
    def __init__(self, port, timeout=60, url_suffix=None):
        deadline = time.monotonic() + timeout
        while True:
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list', timeout=2) as response:
                    targets = json.load(response)
                target = next(t for t in targets if t['type'] == 'page' and not t['url'].startswith('devtools:')
                              and (url_suffix is None or t['url'].split('?')[0].endswith(url_suffix)))
                self.socket = websocket.create_connection(target['webSocketDebuggerUrl'], timeout=5, suppress_origin=True)
                self.counter = 0
                return
            except (OSError, StopIteration):
                if time.monotonic() >= deadline:
                    raise TimeoutError('Editor never exposed a page')
                time.sleep(.25)

    def call(self, method, **params):
        self.counter += 1
        self.socket.send(json.dumps({'id': self.counter, 'method': method, 'params': params}))
        while True:
            message = json.loads(self.socket.recv())
            if message.get('id') == self.counter:
                if 'error' in message:
                    raise RuntimeError(message['error'])
                return message['result']

    def evaluate(self, expression):
        result = self.call('Runtime.evaluate', expression=expression, returnByValue=True, awaitPromise=True)
        if result.get('exceptionDetails'):
            raise RuntimeError(result['exceptionDetails'])
        return result['result'].get('value')

    def key(self, key, code, modifiers=0):
        for kind in ['keyDown', 'keyUp']:
            self.call('Input.dispatchKeyEvent', type=kind, key=key, code=code, modifiers=modifiers,
                      windowsVirtualKeyCode=ord(key.upper()), nativeVirtualKeyCode=ord(key.upper()))

    def click(self, selector):
        point = self.evaluate("""(() => {
          const element = document.querySelector(%s);
          if (!element || !element.offsetHeight) return null;
          const box = element.getBoundingClientRect();
          return {x: box.x + box.width / 2, y: box.y + box.height / 2};
        })()""" % json.dumps(selector))
        if not point:
            return False
        for kind in ['mousePressed', 'mouseReleased']:
            self.call('Input.dispatchMouseEvent', type=kind, button='left', clickCount=1, **point)
        return True

    def screenshot(self, path):
        path.write_bytes(base64.b64decode(self.call('Page.captureScreenshot')['data']))

    def close(self):
        self.socket.close()
