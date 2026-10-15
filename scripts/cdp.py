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
                self.diagnostics = []
                self.requests = {}
                for domain in ['Runtime', 'Log', 'Network']:
                    try:
                        self.call(domain + '.enable')
                    except RuntimeError as error:
                        # Atom's older CDP may lack a diagnostic domain.
                        self.diagnostics.append({'method': domain + '.enable', 'error': str(error)})
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
            if 'method' in message:
                self.record_event(message)
            if message.get('id') == self.counter:
                if 'error' in message:
                    raise RuntimeError(message['error'])
                return message['result']

    def record_event(self, message):
        method = message['method']
        params = message.get('params', {})
        if method == 'Network.requestWillBeSent':
            self.requests[params['requestId']] = params['request']['url']
            if len(self.requests) > 1000:
                self.requests.pop(next(iter(self.requests)))
        if method == 'Network.loadingFailed':
            message['url'] = self.requests.pop(params['requestId'], None)
        elif method == 'Network.loadingFinished':
            self.requests.pop(params['requestId'], None)
        interesting = method in ['Runtime.exceptionThrown', 'Runtime.consoleAPICalled',
                                 'Log.entryAdded', 'Network.loadingFailed']
        if method == 'Network.responseReceived':
            interesting = params['response']['status'] >= 400
        if interesting and len(self.diagnostics) < 500:
            encoded = json.dumps(message)
            self.diagnostics.append(message if len(encoded) < 16000 else {'truncated': encoded[:16000]})

    def save_diagnostics(self, path):
        path.write_text(json.dumps(self.diagnostics, indent=2))

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
