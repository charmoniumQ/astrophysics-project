import asyncio
import re
from pathlib import Path
from typing import Mapping, Union, Any

import charmonium.time_block as ch_time_block
import invoke # type: ignore
from tqdm import tqdm

from util.fabric_pathlib import FabricPath
from util.highlevel_slurm import SlurmJob
from util.util import strhash

ValueType = Union[int, float, str, bool, Path]
ParamsType = Mapping[str, ValueType]

config_line = re.compile("(?m)^\s*(?:(?P<var>\S+)\s*=\s*(?P<val>.+)\s*)|(?:(?://|#).*)$")
def parse_params(enzo_params: str) -> ParamsType:
    config = {}
    for line in enzo_params.split("\n"):
        if line:
            match = config_line.match(line)
            if not match:
                print(repr(line))
                raise RuntimeError()
            if match["var"] and match["val"]:
                config[match["var"]] = match["val"]
    return config

def format_value(value: ValueType) -> str:
    return {True: "1", False: "0"}[value] if isinstance(value, bool) else str(value)

def format_params(enzo_params: ParamsType) -> str:
    return "\n".join(
        f"{var} = {format_value(val)}"
        for var, val in enzo_params.items()
    )


@ch_time_block.decor()
def enzo(
        *args: Any, **kwargs: Any,
) -> None:
    asyncio.run(async_enzo(*args, **kwargs))

async def async_enzo(
    cluster: invoke.Runner,
    bin_dir: Path,
    enzo_params: ParamsType,
    cwd: Path,
    ntasks: int,
    partition: str,
    zstart: int,
) -> None:
    with ch_time_block.ctx("submit to slurm"):
        enzo_params_file = cwd / "enzo_params"
        enzo_params_file.write_text(format_params(enzo_params))
        stdout = cwd / Path("enzo_stdout")
        stderr = cwd / Path("enzo_stderr")
        if stdout.exists():
            stdout.unlink()
        if stderr.exists():
            stderr.unlink()
        job_future = asyncio.create_task(
            SlurmJob.async_submit_with_tenacity(
                command=[
                    bin_dir / "mpirun",
                    "--np",
                    ntasks,
                    bin_dir / "enzo",
                    enzo_params_file,
                ],
                runner=cluster,
                key=strhash(format_params(enzo_params)),
                cwd=cwd,
                ntasks=ntasks,
                cpus_per_task=1,
                partition=partition,
                stdout=stdout,
                stderr=stderr,
            )
        )
        while not job_future.done() and not stdout.exists():
            await asyncio.sleep(1)

    z_line = re.compile("z = (\d+(?:.\d+)?)")
    with ch_time_block.ctx("enzo"):
        with tqdm(total=zstart, desc="z") as progress_bar:
            while not job_future.done():
                match = None
                for match in z_line.finditer(stderr.read_text()):
                    pass
                if match is not None:
                    current_z = float(match.group(1))
                    progress_bar.update(zstart - current_z)
                await asyncio.sleep(1)

        job = await job_future

    print("stdout:")
    print(job.read_stdout())
    print("stderr:")
    print(job.read_stderr())
