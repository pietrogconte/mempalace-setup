"""Windows Task Scheduler registration (daily, only while the user is logged on).

The task runs ``pythonw.exe <this repo>/scripts/mempalace_sync.py`` directly -
no .bat/.ps1/.vbs launcher, so it works with Smart App Control on. Settings:
InteractiveToken (runs only when logged on, no stored password),
StartWhenAvailable (a run missed while the PC was off starts as soon as
possible), IgnoreNew (never two at once), 4 h time limit.
"""

from __future__ import annotations

import datetime as _dt
import os
import subprocess
import sys
import tempfile
from typing import List, Optional
from xml.sax.saxutils import escape

TASK_NAME = "mempalace-sync"


def windowless_python(python: str) -> str:
    """pythonw.exe next to `python`, if present (no console window)."""
    d, base = os.path.split(python)
    if base.lower() == "python.exe":
        candidate = os.path.join(d, "pythonw.exe")
        if os.path.isfile(candidate):
            return candidate
    return python


def build_xml(python: str, script: str, args: List[str], at: str, user: str, workdir: str) -> str:
    hh, mm = (int(x) for x in at.split(":"))
    start = _dt.datetime.combine(_dt.date.today(), _dt.time(hh, mm)).isoformat()
    arguments = " ".join(f'"{a}"' for a in [script] + args)
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>mempalace-sync: daily capture into the MemPalace palace</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{start}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{escape(user)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <ExecutionTimeLimit>PT4H</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(python)}</Command>
      <Arguments>{escape(arguments)}</Arguments>
      <WorkingDirectory>{escape(workdir)}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def _schtasks(args: List[str]) -> int:
    proc = subprocess.run(["schtasks"] + args, capture_output=True, text=True, errors="replace")
    out = (proc.stdout + proc.stderr).strip()
    if out:
        print(out)
    return proc.returncode


def install(at: str, config: Optional[str], python: Optional[str]) -> int:
    if os.name != "nt":
        print("task install is Windows-only")
        return 1
    script = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mempalace_sync.py"))
    py = windowless_python(python or sys.executable)
    args = ["--config", os.path.abspath(os.path.expanduser(config))] if config else []
    user = f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}".lstrip("\\")
    xml = build_xml(py, script, args, at, user, os.path.expanduser("~"))
    fd, tmp = tempfile.mkstemp(suffix=".xml")
    os.close(fd)
    try:
        with open(tmp, "w", encoding="utf-16") as f:
            f.write(xml)
        print(f"registering '{TASK_NAME}': daily {at}, {py} {script}")
        return _schtasks(["/Create", "/TN", TASK_NAME, "/XML", tmp, "/F"])
    finally:
        os.remove(tmp)


def remove() -> int:
    return _schtasks(["/Delete", "/TN", TASK_NAME, "/F"])


def show() -> int:
    return _schtasks(["/Query", "/TN", TASK_NAME, "/V", "/FO", "LIST"])


def run_now() -> int:
    return _schtasks(["/Run", "/TN", TASK_NAME])
