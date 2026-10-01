"""Cgroup v2 CPU accounting includes short-lived and reparented editor children."""
import time


class Cpu:
    def __init__(self, group):
        self.group = group
        self.previous = self.read()

    def read(self):
        values = dict(line.split() for line in (self.group / 'cpu.stat').read_text().splitlines())
        return time.monotonic(), int(values['usage_usec'])

    def sample(self):
        now, usage = self.read()
        before, old_usage = self.previous
        self.previous = now, usage
        if now <= before or usage < old_usage:
            raise RuntimeError('Invalid cgroup CPU accounting')
        return 100 * (usage - old_usage) / ((now - before) * 1_000_000)

