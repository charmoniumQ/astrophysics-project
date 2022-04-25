import asyncio
import datetime
import logging
import sys
from pathlib import Path

import fabric  # type: ignore
from fabric_pathlib import FabricPath
from highlevel_slurm import SlurmJob

logging.basicConfig(stream=sys.stderr, level=logging.INFO)


async def test() -> None:
    with fabric.Connection("cluster") as cluster:

        spack_view = Path("/home/grayson5/project/remote_code/.spack-env/view")
        enzo_params = spack_view / "run/Hydro/Hydro-2D/SedovBlast/SedovBlast.enzo"
        data_dir = FabricPath(cluster, "/home/grayson5/data")
        job = SlurmJob.submit(
            [spack_view / "bin/mpiexec", spack_view / "bin/enzo", enzo_params],
            walltime=datetime.timedelta(minutes=10),
            ntasks=2,
            runner=cluster,
            partition="eng-instruction",
            cwd=data_dir,
            stdout=data_dir / "stdout",
        )
        with job.ensure_termination():
            job.run_to_completion()
            print(job.walltime, job.queued_time, job.memory)
            print(job.read_stdout())
            print(job.read_stderr())


if __name__ == "__main__":
    asyncio.run(test())
