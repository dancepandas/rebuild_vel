"""Windows service wrapper for the Aether panel.

Runs ``web/server.py`` as a Windows service so the panel stays up across
logoffs and reboots, independent of any shell or conversation.  The service
host is Anaconda's base python (it carries pywin32); the panel itself runs on
the training environment's interpreter, so torch and the model stack are the
ones training used.

    # elevated shell:
    python tools/install_service.py install
    python tools/install_service.py start
    python tools/install_service.py stop
    python tools/install_service.py remove

After ``install`` the service starts automatically at boot (Automatic, delayed
start) and restarts on failure.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import win32service
import win32serviceutil
import servicemanager

REPO_ROOT = Path(__file__).resolve().parents[1]
#: the interpreter the panel is verified on - torch, numpy, scipy all live here
APP_PYTHON = r"C:\Users\DELL\.conda\envs\HydroModel\python.exe"
APP_SCRIPT = str(REPO_ROOT / "web" / "server.py")
LOG_DIR = REPO_ROOT / "runs"
LOG_FILE = LOG_DIR / "_service.log"

SERVICE_NAME = "AetherPanel"
SERVICE_DISPLAY = "Aether 断面重建面板"
SERVICE_DESC = ("LAN 展示面板与对外推理接口 (POST /api/reconstruct)，"
                "端口 8760；服务本身不依赖任何登录会话。")


class AetherPanelService(win32serviceutil.ServiceFramework):
    _svc_name_ = SERVICE_NAME
    _svc_display_name_ = SERVICE_DISPLAY
    _svc_description_ = SERVICE_DESC

    def __init__(self, args):
        super().__init__(args)
        self._process = None

    def SvcStop(self):  # noqa: N802 - win32 naming
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        if self._process and self._process.poll() is None:
            # the child reconfigures its own stdio to utf-8 on start; nothing
            # here needs the pipes, so terminate is enough
            self._process.terminate()
            try:
                self._process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self.ReportServiceStatus(win32service.SERVICE_STOPPED)

    def SvcDoRun(self):  # noqa: N802
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        # stdout/stderr go to a file: as a service there is no console, and a
        # full buffer would eventually block the child's writes
        with open(LOG_FILE, "ab", buffering=0) as log:
            self._process = subprocess.Popen(
                [APP_PYTHON, APP_SCRIPT, "--port", "8760"],
                cwd=str(REPO_ROOT),
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            self._process.wait()
        # the panel process ended on its own (crash or bind failure) - report
        # so the service control manager applies its restart-on-failure policy
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_ERROR_TYPE,
            servicemanager.PYS_SERVICE_STOPPED,
            (self._svc_name_, f"panel process exited with {self._process.returncode}"),
        )
        # a non-zero exit inside SvcDoRun marks the service as failed, which is
        # what triggers the recovery action (restart)
        sys.exit(self._process.returncode or 1)


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(AetherPanelService)
