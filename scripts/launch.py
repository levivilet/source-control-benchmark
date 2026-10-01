"""Enter a dedicated cgroup as root, then immediately drop back to the caller."""
import os
import json
from pathlib import Path
import sys


def main():
    group, uid, gid, *command = sys.argv[1:]
    environment = json.load(sys.stdin)
    (Path(group) / 'cgroup.procs').write_text('0')
    os.setgroups([])
    os.setgid(int(gid))
    os.setuid(int(uid))
    os.execvpe(command[0], command, environment)


if __name__ == '__main__':
    main()
