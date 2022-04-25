import asyncio
import sys
import logging
import datetime
from pathlib import Path

import fabric  # type: ignore

from highlevel_slurm import SlurmJob

logging.basicConfig(stream=sys.stderr, level=logging.INFO)

async def test() -> None:
    with fabric.Connection("cluster") as cluster:

        spack_view = Path("/home/grayson5/project/remote_code/.spack-env/view")
        enzo_params = spack_view / "run/Hydro/Hydro-2D/SedovBlast/SedovBlast.enzo"
        job = SlurmJob.submit(
            [spack_view / "bin/mpiexec", spack_view / "bin/enzo", enzo_params],
            walltime=datetime.timedelta(minutes=10),
            runner=cluster,
            partition="eng-instruction",
        )
        with job.ensure_termination():
            await job.run_to_completion()
            print(job.walltime, job.queued_time, job.memory)
            print(job.read_stdout())
            print(job.read_stderr())

asyncio.run(test())
