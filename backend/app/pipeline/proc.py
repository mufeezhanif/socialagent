import asyncio
import subprocess


class ProcError(RuntimeError):
    pass


def _run(cmd: list[str], timeout: float, cwd: str | None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, timeout=timeout, cwd=cwd)


async def run(cmd: list[str], timeout: float = 900, cwd: str | None = None) -> bytes:
    """Run a command in a worker thread (works with any event loop, including Windows selector loops)."""
    try:
        result = await asyncio.to_thread(_run, cmd, timeout, cwd)
    except subprocess.TimeoutExpired as exc:
        raise ProcError(f"{cmd[0]} timed out after {timeout}s") from exc
    if result.returncode != 0:
        tail = result.stderr.decode(errors="ignore")[-2000:]
        raise ProcError(f"{cmd[0]} exited {result.returncode}: {tail}")
    return result.stdout
