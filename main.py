#!/usr/bin/env python3.9

import asyncio
import logging
import multiprocessing
import os
import re
import subprocess
import sys
import zlib
from pathlib import Path
from typing import Generator, Mapping, Union, cast

import charmonium.time_block as ch_time_block
import fabric  # type: ignore
import yaml
from tqdm import tqdm
from charmonium.determ_hash import determ_hash
from charmonium.freeze import freeze

import wrappers
from wrappers.enzo import parse_params as enzo_parse_params
from util.fabric_pathlib import FabricPath
from util.highlevel_slurm import SlurmJob
from util.util import subprocess_run


@ch_time_block.decor()
def main(
    zstart: int = 31,
    grid_depths: list[int] = [5],
    enzo_boxes_per_task: int = 64 ** 3,
    cluster_host: str = "cluster",
    bin_dir_loc: Path = Path("/home/grayson5/project/remote_code/.spack-env/view/bin"),
    data_dir_loc: Path = Path("/scratch/users/grayson5/data"),
    slurm_partition: str = "eng-instruction",
) -> None:

    script_dir = Path(__file__).parent

    with fabric.Connection(cluster_host) as cluster:
        bin_dir = FabricPath(cluster, bin_dir_loc).cast()
        data_dir = FabricPath(cluster, data_dir_loc).cast()

        for grid_depth in grid_depths:

            music_params = yaml.safe_load(((script_dir / "params/music.yaml").read_text()))
            music_params["setup"]["zstart"] = zstart
            music_params["setup"]["levelmin"] = music_params["setup"]["levelmax"] = grid_depth
            key = "{:016x}".format(determ_hash(freeze(music_params)))
            music_output_dir = data_dir / "ic" / key
            if not music_output_dir.exists():
                wrappers.music(
                    cluster=cluster,
                    bin_dir=bin_dir,
                    music_params=music_params,
                    output_dir=music_output_dir,
                )

            generated_enzo_params = enzo_parse_params((music_output_dir / "parameter_file.txt").read_text())
            enzo_paths = [
                music_output_dir / cast(str, generated_enzo_params[f"CosmologySimulationParticle{quantity}{n}Name"])
                for quantity in ["Velocity", "Displacement"]
                for n in range(1, 4)
            ]
            override_enzo_params = yaml.safe_load((script_dir / "params/enzo.yaml").read_text())

            enzo_params = {
                **generated_enzo_params,
                **override_enzo_params,
                "MaximumRefinementLevel": grid_depth,
                "MaximumGravityRefinementLevel": grid_depth,
                "MaximumParticleRefinementLevel": grid_depth,
            }
            key = "{:016x}".format(determ_hash(freeze(enzo_params)))
            enzo_output_dir = data_dir / "enzo" / key
            if not enzo_output_dir.exists():
                enzo_output_dir.mkdir(parents=True)
                for path in enzo_paths:
                    FabricPath.copy(path, enzo_output_dir / path.name)
                wrappers.enzo(
                    cluster=cluster,
                    bin_dir=bin_dir,
                    enzo_params=enzo_params,
                    output_dir=enzo_output_dir,
                    ntasks=max(1, (2 ** grid_depth) ** 3 // enzo_boxes_per_task),
                    slurm_partition=slurm_partition,
                    zstart=zstart,
                    key=key
                )
            print(f"cat {enzo_output_dir!s}/enzo_stdout")
            print((enzo_output_dir / "enzo_stdout").read_text())
            print(f"ls {enzo_output_dir!s}")
            print("\n".join(map(str, enzo_output_dir.iterdir())))
            for file in (enzo_output_dir / "RD0001/")


if __name__ == "__main__":
    main()
