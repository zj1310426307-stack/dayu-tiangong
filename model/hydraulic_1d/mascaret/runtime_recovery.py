"""Crash-safe MASCARET runtime ownership and abandoned-attempt recovery."""

from __future__ import annotations

import os
import signal
import sys
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from re import fullmatch
from shutil import which
from subprocess import DEVNULL, PIPE, Popen, TimeoutExpired, run
from time import monotonic, sleep
from typing import Any

from model.hydraulic_1d.errors import Hydraulic1DExecutionError
from model.hydraulic_1d.mascaret.workspace import (
    cleanup_verified_workspace,
    find_attempt_workspaces,
    read_workspace_marker,
    update_workspace_marker,
)


CONTAINER_LABEL_KEY = "dayu.mascaret.attempt"
PROCESS_IDENTITY_ENV = "DAYU_MASCARET_ATTEMPT_ID"
RUNTIME_HANDLE_SCHEMA = "dayu.mascaret-runtime-handle.v1"


@dataclass(frozen=True, slots=True)
class AttemptRecoveryOutcome:
    """Report whether an abandoned attempt was proven stopped and removed."""

    safe: bool
    detail: str


def _command_sha256(command: tuple[str, ...]) -> str:
    """Fingerprint an argv vector using the same NUL framing exposed by Linux procfs."""

    encoded = b"".join(item.encode("utf-8") + b"\0" for item in command)
    return sha256(encoded).hexdigest()


def container_attempt_label(job_id: str) -> str:
    """Return a Docker-safe opaque label value unique to one execution lease."""

    return sha256(job_id.encode("utf-8")).hexdigest()


def mark_runtime_launching(
    workspace: Path,
    *,
    runtime_kind: str,
    command: tuple[str, ...],
    container_label: str | None,
) -> str:
    """Persist intent before spawning so a crash window never looks safely idle."""

    marker = read_workspace_marker(workspace)
    process_identity = container_attempt_label(str(marker["job_id"]))
    update_workspace_marker(
        workspace,
        state="launching",
        runtime_kind=runtime_kind,
        command_sha256=_command_sha256(command),
        container_label=container_label,
        process_identity=process_identity,
        runtime_handle=None,
    )
    return process_identity


def mark_runtime_exited(workspace: Path, *, return_code: int | None) -> None:
    """Record that the attached launcher returned before parsing or cleanup."""

    update_workspace_marker(
        workspace,
        state="process_exited",
        process_return_code=return_code,
    )


def mark_runtime_released(workspace: Path) -> None:
    """Allow cleanup only after every owned external resource is proven absent."""

    update_workspace_marker(workspace, state="released")


def _linux_process_stat(pid: int) -> dict[str, int] | None:
    """Read only public procfs identity fields before inspecting an owned process."""

    process_root = Path("/proc") / str(pid)
    try:
        raw_stat = (process_root / "stat").read_text(encoding="ascii", errors="strict")
        closing = raw_stat.rfind(")")
        if closing < 0:
            raise ValueError("invalid proc stat")
        fields = raw_stat[closing + 2 :].split()
        if len(fields) < 20:
            raise ValueError("short proc stat")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, ValueError) as exc:
        raise Hydraulic1DExecutionError(
            f"cannot establish Linux MASCARET process identity for pid {pid}: {exc}"
        ) from exc
    return {
        "pid": pid,
        "process_group_id": int(fields[2]),
        "session_id": int(fields[3]),
        "start_time_ticks": int(fields[19]),
    }


def _linux_process(pid: int) -> dict[str, Any] | None:
    """Read argv, cwd, and inherited attempt token for a candidate owned process."""

    identity = _linux_process_stat(pid)
    if identity is None:
        return None
    process_root = Path("/proc") / str(pid)
    try:
        command_line = (process_root / "cmdline").read_bytes()
        cwd = (process_root / "cwd").resolve(strict=True)
        environment = (process_root / "environ").read_bytes().split(b"\0")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, ValueError) as exc:
        raise Hydraulic1DExecutionError(
            f"cannot establish Linux MASCARET process identity for pid {pid}: {exc}"
        ) from exc
    identity_value: str | None = None
    prefix = PROCESS_IDENTITY_ENV.encode("ascii") + b"="
    for item in environment:
        if item.startswith(prefix):
            try:
                identity_value = item[len(prefix) :].decode("ascii", errors="strict")
            except UnicodeError as exc:
                raise Hydraulic1DExecutionError(
                    f"invalid MASCARET process token for pid {pid}"
                ) from exc
            break
    return {
        **identity,
        "cwd": str(cwd),
        "command_sha256": sha256(command_line).hexdigest(),
        "process_identity": identity_value,
    }


if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _JOB_OBJECT_TERMINATE = 0x0008
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
    _ERROR_ALREADY_EXISTS = 183
    _STILL_ACTIVE = 259

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimitInformation),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _KERNEL32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _KERNEL32.CreateJobObjectW.restype = wintypes.HANDLE
    _KERNEL32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    _KERNEL32.SetInformationJobObject.restype = wintypes.BOOL
    _KERNEL32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _KERNEL32.AssignProcessToJobObject.restype = wintypes.BOOL
    _KERNEL32.OpenJobObjectW.argtypes = [
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    _KERNEL32.OpenJobObjectW.restype = wintypes.HANDLE
    _KERNEL32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _KERNEL32.TerminateJobObject.restype = wintypes.BOOL
    _KERNEL32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _KERNEL32.OpenProcess.restype = wintypes.HANDLE
    _KERNEL32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    _KERNEL32.GetProcessTimes.restype = wintypes.BOOL
    _KERNEL32.GetExitCodeProcess.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _KERNEL32.GetExitCodeProcess.restype = wintypes.BOOL
    _KERNEL32.CloseHandle.argtypes = [wintypes.HANDLE]
    _KERNEL32.CloseHandle.restype = wintypes.BOOL


def _windows_creation_time_from_handle(handle: int) -> int:
    """Return the Windows FILETIME creation token held by an exact process handle."""

    if os.name != "nt":
        raise Hydraulic1DExecutionError(
            "Windows process identity requested on another OS"
        )
    created = wintypes.FILETIME()
    exited = wintypes.FILETIME()
    kernel = wintypes.FILETIME()
    user = wintypes.FILETIME()
    if not _KERNEL32.GetProcessTimes(
        handle,
        ctypes.byref(created),
        ctypes.byref(exited),
        ctypes.byref(kernel),
        ctypes.byref(user),
    ):
        raise Hydraulic1DExecutionError(
            f"cannot read Windows process creation time: {ctypes.get_last_error()}"
        )
    return (int(created.dwHighDateTime) << 32) | int(created.dwLowDateTime)


def _windows_process_observation(pid: int) -> tuple[int, bool] | None:
    """Return a PID's creation token and liveness from one exact open handle."""

    if os.name != "nt":
        return None
    handle = _KERNEL32.OpenProcess(
        _PROCESS_QUERY_LIMITED_INFORMATION,
        False,
        pid,
    )
    if not handle:
        return None
    try:
        creation_time = _windows_creation_time_from_handle(handle)
        exit_code = wintypes.DWORD()
        if not _KERNEL32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            raise Hydraulic1DExecutionError(
                f"cannot read Windows process exit code: {ctypes.get_last_error()}"
            )
        return creation_time, int(exit_code.value) == _STILL_ACTIVE
    finally:
        _KERNEL32.CloseHandle(handle)


@dataclass(slots=True)
class RuntimeProcessGuard:
    """Keep a live OS ownership handle until the launcher and all children exit."""

    process: Popen[bytes]
    workspace: Path
    runtime_handle: dict[str, Any] | None = None
    windows_job_handle: int | None = None

    def terminate(self) -> None:
        """Terminate only the process group/job object created for this exact launcher."""

        if os.name == "nt":
            if self.windows_job_handle is None or not _KERNEL32.TerminateJobObject(
                self.windows_job_handle,
                1,
            ):
                raise Hydraulic1DExecutionError(
                    "owned MASCARET Windows Job Object could not be terminated"
                )
            if self.process.poll() is None:
                try:
                    self.process.wait(timeout=5)
                except TimeoutExpired as exc:
                    raise Hydraulic1DExecutionError(
                        "owned MASCARET Windows Job Object resisted termination"
                    ) from exc
            return
        if not sys.platform.startswith("linux") or self.runtime_handle is None:
            raise Hydraulic1DExecutionError(
                "MASCARET process group lacks a validated runtime handle"
            )
        recovered = _recover_linux_group(self.workspace, self.runtime_handle)
        if not recovered.safe:
            raise Hydraulic1DExecutionError(recovered.detail)
        if self.process.poll() is None:
            try:
                self.process.wait(timeout=5)
            except TimeoutExpired as exc:
                raise Hydraulic1DExecutionError(
                    "MASCARET launcher did not exit after its process group stopped"
                ) from exc

    def close(self) -> None:
        """Release a Windows kill-on-close handle after the launcher has exited."""

        if os.name == "nt" and self.windows_job_handle is not None:
            _KERNEL32.CloseHandle(self.windows_job_handle)
            self.windows_job_handle = None


def attach_runtime_process(
    workspace: Path,
    process: Popen[bytes],
    *,
    runtime_kind: str,
    command: tuple[str, ...],
) -> RuntimeProcessGuard:
    """Attach a launcher to a crash-safe OS boundary and persist its identity."""

    marker = read_workspace_marker(workspace)
    expected_command = _command_sha256(command)
    process_identity = marker.get("process_identity")
    if (
        marker.get("state") != "launching"
        or marker.get("command_sha256") != expected_command
        or not isinstance(process_identity, str)
        or not process_identity
    ):
        raise Hydraulic1DExecutionError(
            "runtime launch does not match its workspace marker"
        )
    handle: dict[str, Any] = {
        "schema_version": RUNTIME_HANDLE_SCHEMA,
        "runtime_kind": runtime_kind,
        "pid": process.pid,
        "command_sha256": expected_command,
        "process_identity": process_identity,
    }
    guard = RuntimeProcessGuard(process=process, workspace=workspace)
    if os.name == "nt":
        job_name = (
            "DayuMascaret-" + sha256(str(marker["job_id"]).encode("utf-8")).hexdigest()
        )
        ctypes.set_last_error(0)
        job_handle = _KERNEL32.CreateJobObjectW(None, job_name)
        if not job_handle:
            raise Hydraulic1DExecutionError(
                f"cannot create MASCARET Windows Job Object: {ctypes.get_last_error()}"
            )
        guard.windows_job_handle = int(job_handle)
        if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
            guard.close()
            raise Hydraulic1DExecutionError(
                "MASCARET Windows Job Object identity collision"
            )
        limits = _ExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not _KERNEL32.SetInformationJobObject(
            job_handle,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ) or not _KERNEL32.AssignProcessToJobObject(
            job_handle,
            wintypes.HANDLE(int(process._handle)),
        ):
            error = ctypes.get_last_error()
            guard.close()
            raise Hydraulic1DExecutionError(
                f"cannot place MASCARET in a kill-on-close Windows Job Object: {error}"
            )
        handle.update(
            {
                "platform": "windows",
                "windows_job_name": job_name,
                "process_creation_time": _windows_creation_time_from_handle(
                    int(process._handle)
                ),
            }
        )
    elif sys.platform.startswith("linux"):
        identity = _linux_process(process.pid)
        if identity is None:
            raise Hydraulic1DExecutionError(
                "MASCARET process exited before its group identity was secured"
            )
        else:
            resolved_workspace = str(workspace.resolve())

            def matches(observed: dict[str, Any]) -> bool:
                """Check all public and secret ownership factors together."""

                return (
                    observed["process_group_id"] == process.pid
                    and observed["session_id"] == process.pid
                    and observed["cwd"] == resolved_workspace
                    and observed["command_sha256"] == expected_command
                    and observed["process_identity"] == process_identity
                )

            identity_matches = matches(identity)
            identity_deadline = monotonic() + 1.0
            while (
                not identity_matches
                and process.poll() is None
                and monotonic() < identity_deadline
            ):
                # WSL can briefly expose the new session before procfs publishes
                # the post-exec argv and inherited environment. Never weaken the
                # factors; wait for one coherent observation instead.
                sleep(0.01)
                observed = _linux_process(process.pid)
                if observed is None:
                    break
                identity = observed
                identity_matches = matches(identity)
            if not identity_matches and process.poll() is not None:
                # Very short native runs can become zombies before procfs argv and
                # environ are read. Popen still owns the exact unreused PID. Accept
                # that race only after reaping the direct child and proving that
                # every remaining member of its new session carries our token, or
                # that the session is already empty.
                try:
                    _linux_group_members(
                        process_group_id=process.pid,
                        session_id=process.pid,
                        workspace=workspace,
                        minimum_start_time=int(identity["start_time_ticks"]),
                        process_identity=process_identity,
                    )
                except Hydraulic1DExecutionError:
                    pass
                else:
                    identity = {
                        **identity,
                        "command_sha256": expected_command,
                        "process_identity": process_identity,
                        "leader_exited_before_attach": True,
                    }
                    identity_matches = True
            if not identity_matches:
                raise Hydraulic1DExecutionError(
                    "MASCARET Linux launcher does not own the expected session/workspace "
                    f"(pgid_match={identity['process_group_id'] == process.pid}, "
                    f"sid_match={identity['session_id'] == process.pid}, "
                    f"cwd_match={identity['cwd'] == resolved_workspace}, "
                    f"argv_match={identity['command_sha256'] == expected_command}, "
                    f"attempt_match={identity['process_identity'] == process_identity})"
                )
            handle.update({"platform": "linux", **identity})
    else:
        raise Hydraulic1DExecutionError(
            "crash-safe MASCARET process identity is supported only on Linux and Windows"
        )
    guard.runtime_handle = handle
    try:
        update_workspace_marker(workspace, state="running", runtime_handle=handle)
    except Exception:
        try:
            guard.terminate()
        finally:
            guard.close()
        raise
    return guard


def _linux_group_members(
    *,
    process_group_id: int,
    session_id: int,
    workspace: Path,
    minimum_start_time: int,
    process_identity: str,
) -> list[dict[str, Any]]:
    """Enumerate only members that still prove the recorded group owns this workspace."""

    members: list[dict[str, Any]] = []
    for item in Path("/proc").iterdir():
        if not item.name.isdigit():
            continue
        public_identity = _linux_process_stat(int(item.name))
        if public_identity is None:
            continue
        if (
            public_identity["process_group_id"] != process_group_id
            or public_identity["session_id"] != session_id
        ):
            continue
        identity = _linux_process(int(item.name))
        if identity is None:
            continue
        if (
            identity["cwd"] != str(workspace.resolve())
            or identity["start_time_ticks"] < minimum_start_time
            or identity["process_identity"] != process_identity
        ):
            raise Hydraulic1DExecutionError(
                "recorded MASCARET process group now contains an unowned process"
            )
        members.append(identity)
    return members


def _recover_linux_group(
    workspace: Path, handle: dict[str, Any]
) -> AttemptRecoveryOutcome:
    """Terminate a Linux session only after start-time, cwd, and argv verification."""

    required = (
        "pid",
        "process_group_id",
        "session_id",
        "start_time_ticks",
        "command_sha256",
        "process_identity",
    )
    if (
        any(
            isinstance(handle.get(key), bool) or not isinstance(handle.get(key), int)
            for key in required[:4]
        )
        or not isinstance(handle.get("command_sha256"), str)
        or not isinstance(handle.get("process_identity"), str)
    ):
        return AttemptRecoveryOutcome(False, "Linux runtime handle is incomplete")
    pid = int(handle["pid"])
    group = int(handle["process_group_id"])
    session = int(handle["session_id"])
    started = int(handle["start_time_ticks"])
    process_identity = str(handle["process_identity"])
    try:
        members = _linux_group_members(
            process_group_id=group,
            session_id=session,
            workspace=workspace,
            minimum_start_time=started,
            process_identity=process_identity,
        )
    except Hydraulic1DExecutionError as exc:
        return AttemptRecoveryOutcome(False, str(exc))
    if not members:
        return AttemptRecoveryOutcome(
            True, "recorded Linux process group already exited"
        )
    leader = next((item for item in members if item["pid"] == pid), None)
    if leader is not None and (
        leader["start_time_ticks"] != started
        or leader["command_sha256"] != handle["command_sha256"]
    ):
        return AttemptRecoveryOutcome(
            False, "Linux launcher PID was reused; no process was killed"
        )
    try:
        os.killpg(group, signal.SIGTERM)
    except ProcessLookupError:
        return AttemptRecoveryOutcome(
            True, "recorded Linux process group already exited"
        )
    except (PermissionError, OSError) as exc:
        return AttemptRecoveryOutcome(
            False, f"cannot terminate owned Linux process group: {exc}"
        )
    deadline = monotonic() + 5.0
    while monotonic() < deadline:
        try:
            if not _linux_group_members(
                process_group_id=group,
                session_id=session,
                workspace=workspace,
                minimum_start_time=started,
                process_identity=process_identity,
            ):
                return AttemptRecoveryOutcome(
                    True, "owned Linux process group terminated"
                )
        except Hydraulic1DExecutionError as exc:
            return AttemptRecoveryOutcome(False, str(exc))
        sleep(0.05)
    try:
        remaining = _linux_group_members(
            process_group_id=group,
            session_id=session,
            workspace=workspace,
            minimum_start_time=started,
            process_identity=process_identity,
        )
        if remaining:
            try:
                os.killpg(group, signal.SIGKILL)
            except ProcessLookupError:
                return AttemptRecoveryOutcome(
                    True,
                    "owned Linux process group exited before force termination",
                )
    except (Hydraulic1DExecutionError, PermissionError, OSError) as exc:
        return AttemptRecoveryOutcome(
            False, f"cannot force-stop owned Linux process group: {exc}"
        )
    deadline = monotonic() + 5.0
    while monotonic() < deadline:
        try:
            if not _linux_group_members(
                process_group_id=group,
                session_id=session,
                workspace=workspace,
                minimum_start_time=started,
                process_identity=process_identity,
            ):
                return AttemptRecoveryOutcome(
                    True, "owned Linux process group force-terminated"
                )
        except Hydraulic1DExecutionError as exc:
            return AttemptRecoveryOutcome(False, str(exc))
        sleep(0.05)
    return AttemptRecoveryOutcome(False, "owned Linux process group did not terminate")


def _recover_windows_job(handle: dict[str, Any]) -> AttemptRecoveryOutcome:
    """Terminate a named Windows Job Object without ever targeting a bare reused PID."""

    if os.name != "nt":
        return AttemptRecoveryOutcome(
            False, "Windows runtime handle found on another OS"
        )
    pid = handle.get("pid")
    created = handle.get("process_creation_time")
    job_name = handle.get("windows_job_name")
    if (
        isinstance(pid, bool)
        or not isinstance(pid, int)
        or isinstance(created, bool)
        or not isinstance(created, int)
        or not isinstance(job_name, str)
        or not job_name
    ):
        return AttemptRecoveryOutcome(False, "Windows runtime handle is incomplete")
    job = _KERNEL32.OpenJobObjectW(_JOB_OBJECT_TERMINATE, False, job_name)
    if not job:
        observed = _windows_process_observation(pid)
        if observed is None or observed[0] != created or not observed[1]:
            return AttemptRecoveryOutcome(
                True,
                "owned Windows Job Object exited; any reused PID was left untouched",
            )
        return AttemptRecoveryOutcome(
            False,
            "matching Windows launcher remains but its owned Job Object is unavailable",
        )
    try:
        if not _KERNEL32.TerminateJobObject(job, 1):
            return AttemptRecoveryOutcome(
                False,
                f"cannot terminate owned Windows Job Object: {ctypes.get_last_error()}",
            )
    finally:
        _KERNEL32.CloseHandle(job)
    deadline = monotonic() + 5.0
    while monotonic() < deadline:
        observed = _windows_process_observation(pid)
        if observed is None or observed[0] != created or not observed[1]:
            return AttemptRecoveryOutcome(True, "owned Windows Job Object terminated")
        sleep(0.05)
    return AttemptRecoveryOutcome(
        False, "owned Windows launcher did not leave its Job Object"
    )


def _docker_absent(detail: bytes) -> bool:
    """Recognize Docker's factual not-found response without accepting daemon errors."""

    normalized = detail.decode("utf-8", errors="replace").lower()
    return "no such container" in normalized or "no such object" in normalized


def _recover_container(
    workspace: Path,
    *,
    expected_label: str,
    process_exited: bool,
) -> AttemptRecoveryOutcome:
    """Remove only a cidfile container whose immutable attempt label matches."""

    cidfile = workspace / ".mascaret-container.cid"
    if cidfile.is_symlink():
        return AttemptRecoveryOutcome(False, "MASCARET container cidfile is a symlink")
    if not cidfile.is_file():
        return (
            AttemptRecoveryOutcome(
                True, "container launcher exited before creating a cidfile"
            )
            if process_exited
            else AttemptRecoveryOutcome(
                False, "running container attempt has no cidfile"
            )
        )
    try:
        container_id = cidfile.read_text(encoding="ascii", errors="strict").strip()
    except (OSError, UnicodeError) as exc:
        return AttemptRecoveryOutcome(False, f"cannot read MASCARET cidfile: {exc}")
    if fullmatch(r"[0-9a-fA-F]{12,64}", container_id) is None:
        return AttemptRecoveryOutcome(
            False, "MASCARET cidfile contains an invalid identity"
        )
    docker = which("docker")
    if docker is None:
        return AttemptRecoveryOutcome(
            False, "Docker is unavailable for orphan recovery"
        )
    label_format = '{{ index .Config.Labels "' + CONTAINER_LABEL_KEY + '" }}'
    inspected = run(
        (docker, "inspect", "--format", label_format, container_id),
        stdin=DEVNULL,
        stdout=PIPE,
        stderr=PIPE,
        check=False,
        shell=False,
    )
    if inspected.returncode != 0:
        if _docker_absent(inspected.stdout + inspected.stderr):
            return AttemptRecoveryOutcome(
                True, "recorded MASCARET container already exited"
            )
        return AttemptRecoveryOutcome(
            False, "Docker could not verify the recorded container"
        )
    if inspected.stdout.decode("utf-8", errors="strict").strip() != expected_label:
        return AttemptRecoveryOutcome(
            False, "container identity label mismatch; nothing was killed"
        )
    removed = run(
        (docker, "rm", "--force", container_id),
        stdin=DEVNULL,
        stdout=PIPE,
        stderr=PIPE,
        check=False,
        shell=False,
    )
    if removed.returncode != 0 and not _docker_absent(removed.stdout + removed.stderr):
        return AttemptRecoveryOutcome(
            False, "owned MASCARET container could not be removed"
        )
    verified = run(
        (docker, "inspect", container_id),
        stdin=DEVNULL,
        stdout=PIPE,
        stderr=PIPE,
        check=False,
        shell=False,
    )
    if verified.returncode == 0 or not _docker_absent(
        verified.stdout + verified.stderr
    ):
        return AttemptRecoveryOutcome(
            False, "owned MASCARET container removal was not confirmed"
        )
    return AttemptRecoveryOutcome(True, "owned MASCARET container removed")


def remove_owned_container(
    workspace: Path,
    *,
    expected_label: str,
    process_exited: bool,
) -> None:
    """Raise unless the exact cidfile/label container is confirmed absent."""

    outcome = _recover_container(
        workspace,
        expected_label=expected_label,
        process_exited=process_exited,
    )
    if not outcome.safe:
        raise Hydraulic1DExecutionError(outcome.detail)


def _recover_runtime(workspace: Path, marker: dict[str, Any]) -> AttemptRecoveryOutcome:
    """Recover the external resource named by one validated workspace marker."""

    state = marker.get("state")
    if state == "created":
        return AttemptRecoveryOutcome(True, "workspace existed before runtime launch")
    if state in {"released", "recovered"}:
        return AttemptRecoveryOutcome(True, "workspace runtime was already released")
    if state == "launching":
        return AttemptRecoveryOutcome(
            False,
            "worker disappeared during the unidentifiable process launch window",
        )
    if state not in {"running", "process_exited"}:
        return AttemptRecoveryOutcome(
            False, f"unknown workspace runtime state: {state!r}"
        )
    process_exited = state == "process_exited"
    handle = marker.get("runtime_handle")
    if (
        not isinstance(handle, dict)
        or handle.get("schema_version") != RUNTIME_HANDLE_SCHEMA
    ):
        return AttemptRecoveryOutcome(
            False, "workspace lacks a validated runtime handle"
        )
    runtime_kind = handle.get("runtime_kind")
    if runtime_kind == "container":
        expected_label = marker.get("container_label")
        if not isinstance(expected_label, str) or not expected_label:
            return AttemptRecoveryOutcome(
                False, "container workspace lacks its attempt label"
            )
        container = _recover_container(
            workspace,
            expected_label=expected_label,
            process_exited=process_exited,
        )
        if not container.safe:
            return container
    if handle.get("process_exited_before_identity") is True:
        return AttemptRecoveryOutcome(
            False,
            "runtime exited before its process-group identity was secured",
        )
    platform = handle.get("platform")
    if platform == "linux":
        return _recover_linux_group(workspace, handle)
    if platform == "windows":
        return _recover_windows_job(handle)
    return AttemptRecoveryOutcome(False, "runtime handle names an unsupported platform")


def recover_abandoned_attempt(
    root: Path,
    *,
    job_id: str,
    allow_missing: bool = False,
) -> AttemptRecoveryOutcome:
    """Stop and delete one exact attempt, failing closed on every identity ambiguity."""

    matches = find_attempt_workspaces(root, job_id=job_id)
    if not matches and allow_missing:
        return AttemptRecoveryOutcome(
            True,
            f"no workspace exists for non-runtime phase of {job_id!r}",
        )
    if len(matches) != 1:
        return AttemptRecoveryOutcome(
            False,
            f"expected one marked workspace for {job_id!r}, found {len(matches)}",
        )
    workspace = matches[0]
    try:
        marker = read_workspace_marker(workspace)
        recovered = _recover_runtime(workspace, marker)
        if not recovered.safe:
            return recovered
        update_workspace_marker(workspace, state="recovered")
        cleanup_verified_workspace(root, workspace, job_id=job_id)
    except (Hydraulic1DExecutionError, OSError) as exc:
        return AttemptRecoveryOutcome(False, str(exc))
    return AttemptRecoveryOutcome(True, recovered.detail + "; workspace removed")


__all__ = [
    "AttemptRecoveryOutcome",
    "CONTAINER_LABEL_KEY",
    "PROCESS_IDENTITY_ENV",
    "RuntimeProcessGuard",
    "attach_runtime_process",
    "container_attempt_label",
    "mark_runtime_exited",
    "mark_runtime_launching",
    "mark_runtime_released",
    "recover_abandoned_attempt",
    "remove_owned_container",
]
