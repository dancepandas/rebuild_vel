"""Install / start / stop / remove the Aether panel Windows service.

Thin wrapper around ``tools/panel_service.py`` that adds the recovery policy
(restart on failure) after install, which ServiceFramework itself cannot set.

    python tools/install_service.py install   # then: start
    python tools/install_service.py start
    python tools/install_service.py stop
    python tools/install_service.py remove
    python tools/install_service.py status

Needs an elevated shell (Run as Administrator).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WRAPPER = HERE / "panel_service.py"

#: what the service control manager does when the panel process dies:
#: restart after 5 s, then 30 s, then 60 s, giving up after three tries a day
RECOVERY = ["sc", "failure", "AetherPanel", "reset= 86400", "actions= restart/5000/restart/30000/restart/60000"]


def run(args: list[str]) -> int:
    proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=180)
    # print through a gbk-safe write: the console here is GBK and sc's output
    # carries replacement characters that a bare print would choke on
    out = proc.stdout.encode(sys.stdout.encoding or "utf-8", errors="replace")
    err = proc.stderr.encode(sys.stderr.encoding or "utf-8", errors="replace")
    if out.strip():
        sys.stdout.buffer.write(out)
    if err.strip():
        sys.stderr.buffer.write(err)
    return proc.returncode


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    command = sys.argv[1]
    if command == "status":
        return run(["sc", "query", "AetherPanel"])
    if command == "install":
        code = run([sys.executable, str(WRAPPER), "install"])
        if code == 0:
            run(RECOVERY)
            print("installed; recovery policy = restart on failure (5s/30s/60s); "
                  "start it with: python tools/install_service.py start")
        return code
    return run([sys.executable, str(WRAPPER), command])


if __name__ == "__main__":
    raise SystemExit(main())
