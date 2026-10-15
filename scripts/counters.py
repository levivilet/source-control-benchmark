"""Measure hardware instructions for tasks in a dedicated cgroup."""
import errno
import os
import json
import sys
from pathlib import Path
import select
import signal
import subprocess
import time
import uuid


def parse_counter(raw, cgroup=True):
    rows = [line.split(';') for line in raw.splitlines()
            if len(line.split(';')) >= 6 and line.split(';')[2].strip() == 'instructions']
    if len(rows) != 1:
        raise ValueError('expected exactly one instruction count')
    row = rows[0]
    runtime_column = 4 if cgroup else 3
    try:
        count, runtime, running = int(row[0]), int(row[runtime_column]), float(row[runtime_column + 1])
    except ValueError as error:
        raise ValueError('unsupported or uncounted hardware instructions') from error
    if count <= 0 or runtime <= 0 or not 99.9 <= running <= 100:
        raise ValueError('invalid or multiplexed instruction measurement')
    return count


class Capture:
    def __init__(self, perf, directory, group=None, create_group=False, mode="cgroup"):
        if mode not in ("cgroup", "task"):
            raise ValueError("unknown instruction capture mode")
        self.mode = mode
        self.directory = Path(directory)
        self.perf = perf
        self.group = Path(group) if group else Path('/sys/fs/cgroup') / ('source-control-' + uuid.uuid4().hex)
        self.create_group = create_group or group is None
        self.process = None
        self.fds = []
        self.children = []
        self.enabled = False

    def __enter__(self):
        if self.create_group:
            self.group.mkdir()
        if not (self.group / 'cgroup.procs').exists():
            raise RuntimeError(f'cgroup does not exist: {self.group}')
        try:
            self.perf_version = subprocess.run([self.perf, '--version'], check=True, capture_output=True,
                                                text=True).stdout.strip()
            for name in ['control', 'ack']:
                path = self.directory / name
                os.mkfifo(path)
                self.fds.append(os.open(path, os.O_RDWR | os.O_NONBLOCK))
            self.log = (self.directory / 'perf.log').open('w')
            if self.mode == "cgroup":
                self.open_counter(["-a", "-G", self.group.name])
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def open_counter(self, scope):
        self.process = subprocess.Popen([
            self.perf, "stat", "-e", "instructions", *scope,
            "-x", ";", "-D", "-1", "--control", f"fd:{self.fds[0]},{self.fds[1]}",
        ], pass_fds=tuple(self.fds), stdout=subprocess.DEVNULL, stderr=self.log,
            start_new_session=True)
        # Attaching must finish before the gated launcher can fork or exec.
        self.control("ping")

    def control(self, command):
        before = time.monotonic()
        os.write(self.fds[0], (command + '\n').encode())
        if not select.select([self.fds[1]], [], [], 5)[0]:
            raise RuntimeError(f'perf did not acknowledge {command}')
        if os.read(self.fds[1], 256) not in (b'ack\n', b'ack\n\x00'):
            raise RuntimeError('invalid perf control acknowledgement')
        if self.process.poll() is not None:
            raise RuntimeError('perf exited before cutoff')
        acknowledged = time.monotonic()
        self.enabled = command == 'enable'
        return {'requestedAt': before, 'acknowledgedAt': acknowledged,
                'latencySeconds': acknowledged - before}

    def start(self):
        if self.enabled:
            raise RuntimeError('instruction capture is already enabled')
        self.started = self.control('enable')

    def cutoff(self):
        if not self.enabled:
            raise RuntimeError('instruction capture is not enabled')
        self.stopped = self.control('disable')

    def finish(self):
        if self.enabled:
            raise RuntimeError('instruction capture must be disabled before reading')
        self.process.send_signal(signal.SIGINT)
        status = self.process.wait(timeout=5)
        self.log.flush()
        raw = (self.directory / 'perf.log').read_text()
        if status not in (0, -signal.SIGINT):
            raise RuntimeError(f'perf exited with status {status}: {raw}')
        return {'instructions': parse_counter(raw, cgroup=self.mode == 'cgroup'), 'rawCounter': raw,
                'source': 'perf stat instructions, ' + self.mode, 'perfVersion': self.perf_version,
                'start': self.started, 'cutoff': self.stopped,
                'cutoffAcknowledged': True}

    def launch(self, command, environment, stdout, stderr, cwd=None):
        def enter_group():
            (self.group / 'cgroup.procs').write_text(str(os.getpid()))
            if 'SUDO_UID' in environment:
                os.setgroups([])
                os.setgid(int(environment['SUDO_GID']))
                os.setuid(int(environment['SUDO_UID']))
        actual = command
        if self.mode == 'task':
            actual = [sys.executable, '-c',
                      'import json,os,sys; cmd=json.load(sys.stdin); os.execvpe(cmd[0],cmd,os.environ)']
        child = subprocess.Popen(actual, cwd=cwd, env=environment, stdout=stdout, stderr=stderr,
                                 stdin=subprocess.PIPE if self.mode == 'task' else None,
                                 preexec_fn=enter_group, start_new_session=True)
        self.children.append(child)
        if self.mode == 'task':
            self.open_counter(['-p', str(child.pid)])
            child.stdin.write(json.dumps(command).encode())
            child.stdin.close()
        return child

    def __exit__(self, *args):
        try:
            if self.process and self.process.poll() is None:
                if self.enabled:
                    try:
                        self.cutoff()
                    except (OSError, RuntimeError):
                        pass
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait()
            if self.create_group and self.group.exists():
                (self.group / 'cgroup.kill').write_text('1')
                for child in self.children:
                    child.wait(timeout=5)
                deadline = time.monotonic() + 5
                while True:
                    try:
                        self.group.rmdir()
                        break
                    except OSError as error:
                        if error.errno != errno.EBUSY or time.monotonic() >= deadline:
                            raise
                        time.sleep(.01)
        finally:
            if self.process:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            for fd in self.fds:
                os.close(fd)
            if hasattr(self, 'log'):
                self.log.close()
