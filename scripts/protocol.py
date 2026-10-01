"""Trace-based completion. Empty UI alone is never a completion signal."""
import json
from datetime import datetime

QUIET_SECONDS = 3.0
TIMEOUT_SECONDS = 120.0
CPU_PERCENT_LIMIT = 5.0


def trace_state(path, since=None):
    active = set()
    successful_status = 0
    errors = []
    commands = {}
    started = {}
    if not path.exists():
        return active, successful_status, errors, 0
    lines = path.read_text().splitlines()
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue  # Last append may be in flight; never count it as completion.
        sid = event.get('sid')
        if event.get('event') == 'start':
            active.add(sid)
            commands[sid] = event.get('argv', [])
            started[sid] = datetime.fromisoformat(event['time'].replace('Z', '+00:00')).timestamp() if 'time' in event else None
        elif event.get('event') == 'exit':
            active.discard(sid)
            eligible = since is None or (started.get(sid) is not None and started[sid] >= since)
            if eligible and 'status' in commands.get(sid, []):
                if event.get('code') == 0:
                    successful_status += 1
                else:
                    errors.append(event)
    return active, successful_status, errors, len(lines)


class Completion:
    def __init__(self, baseline, started, require_status=True):
        self.require_status = require_status
        self.baseline = baseline
        self.started = started
        self.quiet_since = None
        self.last_count = None

    def observe(self, now, *, alive, ready, active, statuses, errors, count, cpu_percent=None):
        if not alive:
            raise RuntimeError('Editor exited during measurement')
        if errors:
            raise RuntimeError('Git status failed')
        if now - self.started >= TIMEOUT_SECONDS:
            raise TimeoutError('No proven source-control completion within 120 seconds')
        cpu_idle = cpu_percent is not None and 0 <= cpu_percent <= CPU_PERCENT_LIMIT
        if not ready or active or not cpu_idle or (self.require_status and statuses <= self.baseline):
            self.quiet_since = None
        elif count != self.last_count or self.quiet_since is None:
            self.quiet_since = now
        self.last_count = count
        return self.quiet_since is not None and now - self.quiet_since >= QUIET_SECONDS
