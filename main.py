#!/usr/bin/env python3.10

from typing import Mapping, Generator, Union
import asyncio
import logging
import re
import multiprocessing
import sys
import os
import subprocess
import shutil
import zlib
from pathlib import Path
from util import subprocess_run
from slurmlib import SlurmJob
from tqdm import tqdm  # type: ignore
import charmonium.time_block as ch_time_block  # type: ignore

@ch_time_block.decor()  # type: ignore
def generate_initial_conditions(
        music_params: Mapping[str, Mapping[str, Union[int, float, str, bool]]],
        output_dir: Path,
) -> None:
    tmp_dir = output_dir / "tmp"
    music_params = {
        **music_params,
        "output": {
            "format": "enzo",
            "filename": tmp_dir.name,
        },
    }
    music_params_file = output_dir / "music_params.conf"
    def convert(val: Union[int, float, str, bool]) -> str:
        return {True: "yes", False: "no"}[val] if isinstance(val, bool) else str(val)
    music_params_file.write_text("\n".join([
        "\n".join([
            f"[{section}]",
            "\n".join([
                f"{key} = {convert(val)}"
                for key, val in key_vals.items()
            ]),
            "",
        ])
        for section, key_vals in music_params.items()
    ]))
    subprocess_run(
        ["MUSIC", music_params_file],
        cwd=output_dir,
        env_override={
            "OMP_NUM_THREADS": str(len(os.sched_getaffinity(0))),
        },
    )
    for file in tmp_dir.glob("*"):
        shutil.move(file, output_dir / file.name)
    tmp_dir.rmdir()

@ch_time_block.decor()  # type: ignore
async def run_simulation(enzo_params: str, cwd: Path, ntasks: int, partition: str, zstart: int) -> None:
    with ch_time_block.ctx("submit to slurm"):  # type: ignore
        enzo_params_file = cwd / "enzo_params"
        enzo_params_file.write_text(enzo_params)
        stdout = cwd / Path("enzo_stdout")
        if stdout.exists():
            stdout.unlink()
        job = asyncio.create_task(SlurmJob.async_submit_with_tenacity(
            strhash(enzo_params),
            command=["mpiexec", "enzo", enzo_params_file],
            cwd=cwd,
            ntasks=ntasks,
            cpus_per_task=1,
            partition=partition,
            stdout=stdout,
        ))
        while not job.done():
            if stdout.exists():
                break
            await asyncio.sleep(1)

    with ch_time_block.ctx("enzo"):  # type: ignore
        if match:
            with tqdm(total=zstart, desc="z") as progress_bar:
                while not job.done():
                    for line in stdout.read_text():
                        if match := stdout_line.search(line):
                            current_z = float(match.group(1))
                    progress_bar.update(zstart - current_z)
                    await asyncio.sleep(1)

        await job

def strhash(data: str) -> int:
    return zlib.crc32(data.encode())

logging.basicConfig(stream=sys.stdout, encoding='utf-8', level=logging.DEBUG)
logging.getLogger("charmonium.logger").propagate = False
@ch_time_block.decor()  # type: ignore
def main() -> None:
    zstart = 63
    music_levels = 5
    enzo_boxes_per_task = 64**3
    slurm_partition = "eng-instruction"

    music_params = {
        "setup": {
            # from Illustris
            "boxlength": 106.5,

            # DM only simulation
            "baryons": False,

            # from Illustris
            "zstart": zstart,

            # resolution
            "levelmin": music_levels,
            "levelmax": music_levels,

            # Require subgrids to be always aligned with the coarsest grid? This is necessary for some codes (ENZO) but not for others (Gadget).
            "align_top": True,

            # Consider changing to "ellipsoid"?
            "region": "box",
        },
        "cosmology": {
            "Omega_m": 0.2726,
            "Omega_L": 0.7274,
            "Omega_b": 0.0,
            "H0": 70.4,
            "sigma_8": 0.809,
            "transfer": "bbks",
            "sugiyama_corr": True,
            "nspec": 0.961,
        },
        "random": {
            "seed[3]": 1234,
        }
    }

    root = Path(__file__).resolve().parent
    tmp_dir = root / "data"

    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir()

    generate_initial_conditions(music_params, tmp_dir)

    enzo_params = "\n".join([
        (tmp_dir / "parameter_file.txt").read_text(),
        (root / "additional_parameter_file.txt").read_text(),
    ])

    ntasks = max(1, (2**music_levels)**3 // enzo_boxes_per_task)
    asyncio.run(run_simulation(enzo_params, tmp_dir, ntasks, slurm_partition, zstart))

if __name__ == "__main__":
    main()
