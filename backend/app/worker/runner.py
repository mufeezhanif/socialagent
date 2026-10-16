import asyncio
import logging

from app.config import settings
from app.models import Job
from app.worker import queue
from app.worker.tasks import HANDLERS, HEAVY

log = logging.getLogger(__name__)


class Worker:
    """Two lanes: heavy renders (one at a time by default) and light jobs (chat, captions, publishing)."""

    def __init__(self) -> None:
        self.heavy = asyncio.Semaphore(settings.render_concurrency)
        self.light = asyncio.Semaphore(6)
        self.running: set[asyncio.Task] = set()
        self.stopping = False

    async def run(self) -> None:
        await queue.recover_stuck(older_than_s=0)  # fresh process: nothing is really running
        await asyncio.gather(self._lane(self.heavy, HEAVY, True), self._lane(self.light, HEAVY, False))

    def stop(self) -> None:
        self.stopping = True
        for task in self.running:
            task.cancel()

    async def _lane(self, sem: asyncio.Semaphore, kinds: set[str], include: bool) -> None:
        while not self.stopping:
            await sem.acquire()
            try:
                job = await queue.claim(kinds, include)
            except Exception:
                log.exception("claim failed")
                job = None
            if job is None:
                sem.release()
                await queue.wait_for_work(1.0)
                continue
            task = asyncio.create_task(self._execute(job, sem))
            self.running.add(task)
            task.add_done_callback(self.running.discard)

    async def _execute(self, job: Job, sem: asyncio.Semaphore) -> None:
        try:
            handler = HANDLERS.get(job.kind)
            if handler is None:
                raise RuntimeError(f"no handler for {job.kind}")
            await handler(job)
            await queue.finish(job.id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("job %s (%s) failed", job.id, job.kind)
            await queue.finish(job.id, error=repr(exc))
        finally:
            sem.release()
            queue.wake()
