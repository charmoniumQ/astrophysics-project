"""A high-level Pythonic interface to a Slurm workload manager.

# Why you want a Python API

At first, you may have deployed Slurm jobs by writing a Slurm script and typing
in `sbatch ...`. This has two problems: your commands aren't recorded in a way
that can be rerun by someone else, and you have to remember environmental
details about the scripts (which order to run them, where the output files go,
what they need as input).

As such, you may automate this with a shell script. However, Shell is a tricky
language ([1], [2]) to do certain things. For example, suppose you don't know the proper
timeout of a certain job; you want to try running that job with a timeout of X,
and if it fails due to timeout, try with a timeout of 2x and 4x, and so on until
it succeeds (like exponential backoff). If the timeout is represented in a Shell
variable as "%H:%M:%S", how do you multiply it by 2? This is trivial in a
programming language with an object representation of time. In fact, this
library provides exponential backoff, `submit_with_tenacity`.

[1]: https://samgrayson.me/2021-01-01-shell/
[2]: https://docs.google.com/presentation/d/11vZzXCfAA0aOFAuHA0nAvAzALGFGCH-dqHxx6XMgbk8/edit#slide=id.p

# Piror work

[PySlurm] is a low-level interface that uses the Slurm API directly. This
library is easier to use because it is more Pythonic than just wrapping the C
API in Python functions. For example, SlurmJobs can exist in contextmanager that
cancels them upon exiting.

[submitit] focuses on running Python functions across a cluster, whereas this
library focuses on running external programs.

[simple_slurm] is also a high-level interface, but it doesn't wrap some aspects
in idiomatic Python. For example, the user submits times library as strings of
"%H:%M:%S", whereas this library uses idiomatic `datetime.timedelta`
objects. See the previous section for why this is desirable. However,
simple_slurm supports more options than this library, so if you need a ton of
options, use that.

In addition, none of these libraries incorporate remote access; you would need
to install them on the login node (machine that has Slurm). This library can be run on your
laptop and SSH to the login node.

[PySlurm]: https://github.com/PySlurm/pyslurm
[submitit]: https://github.com/facebookincubator/submitit
[simple_slurm]: https://github.com/amq92/simple_slurm

# Usage

If I've sold you on the idea...

First you need to make a connection:
```python
# For remote:
import fabric
cluster = fabric.Connection("grayson5@cc-login.campuscluster.illinois.edu")
# Must have SSH keys (passwordless login) for this to work.
# Or local:
import invoke
cluster = invoke.Runner(invoke.Context())
```

Ideally you would create Slurm jobs from this library.

```python
job = SlurmJob.submit(
    ["mpiexec", "./test_mpi", input_file],
    partition="eng-instruction",
    ntasks=4,
    cpus_per_task=2,
    cluster=cluster,
    # See SlurmJob.submit for details
)
# or if you want automatic retrying
job = SlurmJob.submit_with_tenacity(
    ...,
    # same arguments as submit
)
```

If you want to wait for the job to finish (e.g. to process the results), you can call

```python
job.run_to_completion()
# or in an async function:
# await job.async_run_to_completion()
```

If you do this, you should take care, you should take care to terminate the job
if the script crashes. Otherwise, you may get these "orphan" jobs that no script
is waiting on its results. This can be done with a context manager:

```python
job = ...
with job.ensure_termination():
    # Actions to do while job is running.
    # If an exception occurs here, the job gets `scancel`ed.

    # This will wait for the job to complete.
    job.run_to_completion()
```

Of course, you don't have to do things this way; You could launch a job and wait
on it in a different script or wait on it manually.

You can also look up jobs that were started before this script based on its `job_id`.

```python
job = Job(job_id)
```

Once you have the job, you can look at its intermediate or final output:

```python
print(job.stdout, job.status, job.walltime)
```

Read the code for more details.

"""

from __future__ import annotations

import asyncio
import contextlib
import datetime
import io
import logging
import shlex
import time
from dataclasses import dataclass
from pathlib import Path
from typing import (
    Any,
    ContextManager,
    Generator,
    Hashable,
    Optional,
    Sequence,
    Tuple,
    Type,
    Union,
    cast,
)

import bitmath  # type: ignore
import invoke  # type: ignore

from .util import PersistentObject, strftimedelta, strptimedelta

logger = logging.getLogger(__name__)
_allocation_cache_manager = PersistentObject[
    dict[Hashable, Tuple[datetime.timedelta, bitmath.Bitmath]]
]({}, "allocation_cache.pkl")
_state_mapping = {
    "BOOT_FAIL": "failed",
    "CANCELLED": "failed-retry",
    "COMPLETED": "success",
    "DEADLINE": "failed",
    "FAILED": "failed",
    "NODE_FAIL": "failed-retry",
    "OUT_OF_MEMORY": "failed-mem",
    "PENDING": "waiting",
    "PREEMPTED": "failed-retry",
    "RUNNING": "waiting",
    "REQUEUED": "waiting",
    "RESIZING": "waiting",
    "REVOKED": "failed",
    "SUSPENDED": "failed",
    "TIMEOUT": "failed-time",
    "": "waiting",
}


@dataclass
class SlurmJob:
    job_id: int
    _runner: invoke.Runner
    _stdout: Optional[Path] = None
    _stderr: Optional[Path] = None
    _running: bool = True

    def read_stdout(self) -> str:
        if self._stdout is None:
            raise RuntimeError(
                "I don't know where stdout for this job is; pass it with SlurmJob(..., stdout=...)"
            )
        if self._stdout.exists():
            return self._stdout.read_text()
        else:
            return ""

    def read_stderr(self) -> str:
        if self._stderr is None:
            raise RuntimeError(
                "I don't know where stderr for this job is; pass it with SlurmJob(..., stderr=...)"
            )
        if self._stderr.exists():
            return self._stderr.read_text()
        else:
            return ""

    def _get_sacct_field(self, field: str) -> str:
        stdout = self._runner.run(
            f"sacct --job={self.job_id} --noheader --parsable2 --format={field}",
            hide="both",
        ).stdout
        value = cast(str, stdout).split("\n")[0].strip()
        return value

    @property
    def status(self) -> str:
        """Returns a "simplified status" of the Slurm job. See _state_mapping."""
        state = self._get_sacct_field("State")
        status = _state_mapping.get(state, state)
        logger.info("Slurm job %d: status = %r, state = %r", self.job_id, status, state)
        if status != "running":
            self._running = False
        return status

    @property
    def walltime(self) -> datetime.timedelta:
        """Returns the walltime used by this job."""
        time = self._get_sacct_field("Elapsed")
        return strptimedelta(time, "%H:%M:%S")

    @property
    def queued_time(self) -> datetime.timedelta:
        """Returns the walltime this job spent in the queue."""
        time = self._get_sacct_field("Reserved")
        return strptimedelta(time, "%H:%M:%S")

    @property
    def nnodes(self) -> int:
        """Returns the number of nodes allocated to this job."""
        return int(self._get_sacct_field("NNodes"))

    @property
    def ncpus(self) -> int:
        """Returns the number of CPUs allocated to this job."""
        return int(self._get_sacct_field("NCPUs"))

    @property
    def memory(self) -> Optional[bitmath.Bitmath]:
        """Returns the maximum size of the resident set (memory) over all nodes, steps, and time."""
        proc = self._runner.run(
            f"sacct --job={self.job_id} --noheader --parsable2 --format=MaxRSS --units=K",
            hide="both",
        )
        values: list[int] = []
        for line in proc.stdout.split("\n"):
            line = line.strip()[:-1]
            if line:
                values.append(int(line))
        return bitmath.KiB(max(values)) if values else None

    def run_to_completion(
        self, wait_time: datetime.timedelta = datetime.timedelta(seconds=15),
    ) -> str:
        """Wait for the job to complete or fail."""
        status = "waiting"
        logger.info(
            "Slurm job %d: checking sacct every %.1fs",
            self.job_id,
            wait_time.total_seconds(),
        )
        while status == "waiting":
            time.sleep(wait_time.total_seconds())
            status = self.status
        return status

    async def async_run_to_completion(
        self, wait_time: datetime.timedelta = datetime.timedelta(seconds=15),
    ) -> str:
        """Wait for the job to complete or fail."""
        status = "waiting"
        logger.info(
            "Slurm job %d: checking sacct every %.1fs",
            self.job_id,
            wait_time.total_seconds(),
        )
        while status == "waiting":
            await asyncio.sleep(wait_time.total_seconds())
            status = self.status
        return status

    @contextlib.contextmanager
    def ensure_termination(self) -> Generator[None, None, None]:
        """Ensures the job is completed, failed, or terminated when exiting the context."""
        try:
            yield
        finally:
            self.terminate()

    def terminate(self) -> None:
        """Cancels the job if it is not completed or failed."""
        if self._running:
            if self.status == "waiting":
                logger.info("Slurm job %d: canceling", self.job_id)
                self._runner.run(f"scancel --job={self.job_id}", hide="both")

    @staticmethod
    def submit(
        command: Sequence[Union[str, Path, int]],
        *,
        runner: invoke.Runner = invoke.Local(invoke.Context()),
        walltime: Optional[datetime.timedelta] = None,
        memory: Union[bitmath.Bitmath, str] = bitmath.KiB(0),
        ntasks: int = 1,
        cpus_per_task: int = 1,
        gpus_per_task: int = 0,
        stdout: Optional[Path] = None,
        stderr: Optional[Path] = None,
        job_name: Optional[str] = None,
        partition: Optional[str] = None,
        cwd: Optional[Path] = None,
        account: Optional[str] = None,
    ) -> SlurmJob:
        """Run a command in Slurm

        The command need not be a Slurm script; it can be a compiled executable
        too. If it is a Slurm script, the Slurm options will be interpreted, but
        the options passed here take precedence.

        Specifying `ntasks` and `cpus_per_task` is more flexible than specifying
        `nodes` and `cpus_per_node` because the scheduler could colocate
        mulitple tasks on the same node. Despite being more flexible for the
        scheduler, it gives you the same number of CPUs. Unless you care about
        per-node resources (usually you only care about the number of CPUs),
        this is more optimal

        I omitted the options for job array. When you have a programatic API,
        Slurm's job array are superfluous.

        """
        memory2 = (
            memory
            if isinstance(memory, bitmath.Bitmath)
            else bitmath.parse_string(memory)
        )
        if stdout is None:
            stdout = Path(runner, Path() / "slurm-%j.out")
        if stderr is None:
            stderr = Path(runner, Path() / "slurm-%j.out")
        stdout.parent.mkdir(exist_ok=True)
        stderr.parent.mkdir(exist_ok=True)
        possibly_slurm_script = Path(cast(Union[str, Path], command[0]))
        is_slurm_script = possibly_slurm_script.exists() and possibly_slurm_script.read_text().startswith(
            "#!"
        )
        command2 = list(map(str, command))
        proc = runner.run(
            shlex.join(
                [
                    "sbatch",
                    *(
                        [f"--time={strftimedelta(walltime, '%D-%H:%M:%S')}"]
                        if walltime
                        else []
                    ),
                    f"--chdir={(cwd if cwd else Path())!s}",
                    f"--ntasks={ntasks}",
                    f"--cpus-per-task={cpus_per_task}",
                    f"--gpus-per-task={gpus_per_task}",
                    *([f"--job-name={job_name}"] if job_name else []),
                    *([f"--partition={partition}"] if partition else []),
                    f"--output={stdout!s}",
                    f"--error={stderr!s}",
                    *([f"--account={account}"] if account else []),
                    *(
                        [f"--wrap={shlex.join(command2)}"]
                        if not is_slurm_script
                        else []
                    ),
                    *([f"--mem={memory2.to_KiB().value:.0f}K"] if memory2 else []),
                    "--parsable",
                    *(command2 if is_slurm_script else []),
                ]
            ),
            hide="both",
        )
        job_id = int(proc.stdout.strip())
        logger.info("Started Slurm job %d", job_id)
        stdout = stdout.parent / stdout.name.replace("%j", str(job_id))
        stderr = stderr.parent / stderr.name.replace("%j", str(job_id))
        return SlurmJob(job_id, runner, stdout, stderr)

    @staticmethod
    async def async_submit_with_tenacity(
        command: Sequence[Union[str, Path, int]],
        *,
        runner: invoke.Runner = invoke.Local(invoke.Context()),
        key: Optional[Hashable] = None,
        walltime: Optional[datetime.timedelta] = None,
        memory: Optional[Union[bitmath.Bitmath, str]] = None,
        ntasks: int = 1,
        cpus_per_task: int = 1,
        gpus_per_task: int = 0,
        stdout: Optional[Path] = None,
        stderr: Optional[Path] = None,
        job_name: Optional[str] = None,
        partition: Optional[str] = None,
        cwd: Optional[Path] = None,
        account: Optional[str] = None,
    ) -> SlurmJob:
        """Submits a job and retries it if we didn't allocate enough resources.

        `submit_and_wait` also remembers the resource utilization of the last
        working run of that `command` + `key`, which it defaults to if
        `walltime` and `memory` are not passed. `key` is a key the user can
        set to differentiate multiple runs of the same command with different
        data (and thus different resource utilization numbers).

        """
        command2 = list(map(str, command))
        real_key = (*command2, key)
        with _allocation_cache_manager.transaction() as allocation_cache:
            # Get the working resource allocation parameters from last time if they are unset.
            if key in allocation_cache:
                if walltime is None:
                    walltime = allocation_cache[key][0]
                if memory is None:
                    memory = allocation_cache[key][1]
        memory2 = (
            memory
            if isinstance(memory, bitmath.Bitmath)
            else bitmath.parse_string(memory)
            if isinstance(memory, str)
            else bitmath.KiB(0)
        )
        walltime2 = walltime if walltime else datetime.timedelta(minutes=5)
        while True:
            job = SlurmJob.submit(
                command=command2,
                runner=runner,
                walltime=walltime2,
                memory=memory2,
                ntasks=ntasks,
                cpus_per_task=cpus_per_task,
                gpus_per_task=gpus_per_task,
                stdout=stdout,
                stderr=stderr,
                job_name=job_name,
                partition=partition,
                cwd=cwd,
                account=account,
            )
            status = await job.async_run_to_completion()
            if status == "failed-mem":
                if memory is None or memory == bitmath.KiB(0):
                    memory2 = bitmath.Bitmath.GiB(4)
                else:
                    memory2 = memory * 3
                logger.info(
                    "Job %r failed for memory; expanding to %r", real_key, memory2
                )
            elif status == "failed-time":
                walltime2 = walltime2 * 3
                logger.info(
                    "Job %r failed for time; expanding to %r", real_key, walltime2
                )
            elif status == "failed-retry":
                logger.info("Job %r failed; retrying", key)
            elif status == "success":
                logger.info("Job %r succeeded; quitting", key)
                with _allocation_cache_manager.transaction() as allocation_cache:
                    elapsed_time = job.walltime
                    used_mem = job.memory
                    safety_factor = 1.5
                    elapsed_time *= safety_factor
                    if used_mem is not None:
                        used_mem *= safety_factor
                    logger.info(
                        "Saving parameters for %r (%r, %r)",
                        real_key,
                        elapsed_time,
                        used_mem,
                    )
                    allocation_cache[key] = (walltime2, memory2)
                return job
            else:
                raise RuntimeError(
                    f"Slurm job {key!s} failed with {status!s}\n{job.read_stdout()}\n{job.read_stderr()}"
                )

    @staticmethod
    def submit_with_tenacity(*args: Any, **kwargs: Any) -> SlurmJob:
        """See async_submit_with_tenacity"""
        return asyncio.run(SlurmJob.async_submit_with_tenacity(*args, **kwargs))
