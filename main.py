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
import invoke  # type: ignore
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
    cluster: invoke.Runner = fabric.Connection("cluster"),
    data_dir: Path = Path("/scratch/users/grayson5/data"),
    spack_dir: Path = Path("/scratch/users/grayson5/spack"),
    spack_env: str = "main4",
    slurm_partition: str = "eng-instruction",
) -> None:

    script_dir = Path(__file__).parent

    prefix_str = f"source {spack_dir!s}/share/spack/setup-env.sh && spack env activate {spack_env}"
    with cluster, cluster.prefix(prefix_str):
        data_dir = FabricPath(cluster, data_dir).cast()

        for grid_depth in grid_depths:

            # Combine MUSIC params with override params.
            music_params = yaml.safe_load(((script_dir / "params/music.yaml").read_text()))
            music_params["setup"]["zstart"] = zstart
            music_params["setup"]["levelmin"] = grid_depth
            music_params["setup"]["levelmax"] = grid_depth

            # Run MUSIC if data does not already exist for this config.
            key = "{:016x}".format(determ_hash(freeze(music_params)))
            music_output_dir = data_dir / "ic" / key
            if not music_output_dir.exists():
                wrappers.music(
                    cluster=cluster,
                    music_params=music_params,
                    output_dir=music_output_dir,
                )

            # These are the files that MUSIC creates.
            generated_enzo_params = enzo_parse_params((music_output_dir / "parameter_file.txt").read_text())
            enzo_paths = [
                music_output_dir / cast(str, generated_enzo_params[f"CosmologySimulationParticle{quantity}{n}Name"])
                for quantity in ["Velocity", "Displacement"]
                for n in range(1, 4)
            ]

            # Combine generated Enzo params with override params
            override_enzo_params = yaml.safe_load((script_dir / "params/enzo.yaml").read_text())
            enzo_params = {
                **generated_enzo_params,
                **override_enzo_params,
                "MaximumRefinementLevel": grid_depth,
                "MaximumGravityRefinementLevel": grid_depth,
                "MaximumParticleRefinementLevel": grid_depth,
            }

            # Run Enzo if the data does not already exist for this config.
            key = "{:016x}".format(determ_hash(freeze(enzo_params)))
            enzo_output_dir = data_dir / "enzo" / key
            if not enzo_output_dir.exists():
                # Copy initial conditions over.
                enzo_output_dir.mkdir(parents=True)
                for path in enzo_paths:
                    (enzo_output_dir / path.name).symlink_to(path)
                wrappers.enzo(
                    cluster=cluster,
                    enzo_params=enzo_params,
                    output_dir=enzo_output_dir,
                    ntasks=max(1, (2 ** grid_depth) ** 3 // enzo_boxes_per_task),
                    slurm_partition=slurm_partition,
                    zstart=zstart,
                    key=key
                )

            data_path = enzo_output_dir / "RD0001/RedshiftOutput0001"

            # Run process_data.py on the data.
            FabricPath.copy(script_dir / "process_data.py", data_dir / "process_data.py")
            cluster.run(f"python {data_dir!s}/process_data.py {data_path}")


if __name__ == "__main__":
    main()
