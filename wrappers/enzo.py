import asyncio
import re
from pathlib import Path
from typing import Any, Mapping, Union, Hashable

import charmonium.time_block as ch_time_block
import invoke  # type: ignore
from tqdm import tqdm

from util.fabric_pathlib import FabricPath
from util.highlevel_slurm import SlurmJob
from util.util import strhash

ValueType = Union[int, float, str, bool, Path]
ParamsType = Mapping[str, ValueType]

def parse_params(enzo_params: str) -> ParamsType:
    config = {}
    for line in enzo_params.split("\n"):
        # Cut off comments
        if "#" in line:
            line = line[:line.find("#")]
        if "//" in line:
            line = line[:line.find("//")]
        line = line.strip()
        if line:
            if "=" not in line:
                raise RuntimeError("{line!r} doesn't look like valid enzo parameter line.")
            else:
                left, _, right = line.partition("=")
                config[left.strip()] = right.strip()
    return config


def format_value(value: ValueType) -> str:
    return {True: "1", False: "0"}[value] if isinstance(value, bool) else str(value)


def format_params(enzo_params: ParamsType) -> str:
    return "\n".join(f"{var} = {format_value(val)}" for var, val in enzo_params.items()) + "\n"


@ch_time_block.decor()
def enzo(*args: Any, **kwargs: Any,) -> None:
    asyncio.run(async_enzo(*args, **kwargs))


async def async_enzo(
    cluster: invoke.Runner,
    enzo_params: ParamsType,
    output_dir: Path,
    ntasks: int,
    zstart: int,
    slurm_partition: str,
    key: Hashable,
) -> None:
    if not output_dir.exists():
        output_dir.mkdir(parents=True)
    with ch_time_block.ctx("submit to slurm"):
        enzo_params_file = output_dir / "enzo_params"
        enzo_params_file.write_text(format_params(enzo_params))
        stdout = output_dir / Path("enzo_stdout")
        stderr = output_dir / Path("enzo_stderr")
        if stdout.exists():
            stdout.unlink()
        if stderr.exists():
            stderr.unlink()
        job_future = asyncio.create_task(
            SlurmJob.async_submit_with_tenacity(
                command=[
                    "mpirun",
                    "--np",
                    ntasks,
                    "enzo",
                    enzo_params_file,
                ],
                runner=cluster,
                key=(strhash(format_params(enzo_params)), key),
                cwd=output_dir,
                ntasks=ntasks,
                cpus_per_task=1,
                partition=slurm_partition,
                stdout=stdout,
                stderr=stderr,
            )
        )
        while not job_future.done() and not stdout.exists():
            await asyncio.sleep(1)

    z_line = re.compile("z = (\d+(?:.\d+)?)")
    last_z = zstart
    with ch_time_block.ctx("enzo"):
        with tqdm(total=zstart, desc="z") as progress_bar:
            while not job_future.done():
                match = None
                for match in z_line.finditer(stderr.read_text()):
                    pass
                if match is not None:
                    current_z = float(match.group(1))
                    progress_bar.update(last_z - current_z)
                    last_z = current_z
                await asyncio.sleep(1)

        job = await job_future
