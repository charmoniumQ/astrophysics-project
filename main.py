#!/usr/bin/env python3.9

from __future__ import annotations

import asyncio
import logging
import multiprocessing
import os
import random
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
from wrappers.enzo import parse_params as enzo_parse_params, ValueType as EnzoValueType
from util.fabric_pathlib import FabricPath
from util.highlevel_slurm import SlurmJob
from util.util import subprocess_run



@ch_time_block.decor()
def main(
    zstart: int = 128,
    grid_depths: list[int] = [4, 7],
    enzo_boxes_per_task: int = 64 ** 3,
    cluster: invoke.Runner = fabric.Connection("cluster"),
    data_dir: Path = Path("/scratch/users/grayson5/data"),
    spack_dir: Path = Path("/scratch/users/grayson5/spack"),
    spack_env: str = "main4",
    slurm_partition: str = "eng-instruction",
    voxels_per_side: int = 64,
    padding: int = 24,
    dt_data_dump: int = 5,
    plot_cosmology: bool = True,
) -> None:

    script_dir = Path(__file__).parent

    random.seed(0)

    data: dict[int, Path] = {}

    prefix_str = f"source {spack_dir!s}/share/spack/setup-env.sh && spack env activate {spack_env}"
    with cluster:
        data_dir = FabricPath(data_dir, cluster).cast()

        for grid_depth in grid_depths:

            cosmology_animation = grid_depth == 7 and not (script_dir / "processed" / "cosmology.gif").exists()

            with ch_time_block.ctx("music preface"):
                # Combine MUSIC params with override params.
                music_params = yaml.safe_load(((script_dir / "params/music.yaml").read_text()))
                music_params["setup"]["zstart"] = zstart
                music_params["setup"]["levelmin"] = grid_depth
                music_params["setup"]["levelmax"] = grid_depth
                # msuic_params["random"]["seed[3]"] = random.randint(0, 9999)

                # Run MUSIC if data does not already exist for this config.
                key = "{:016x}".format(determ_hash(freeze(music_params)))
                music_output_dir = data_dir / "ic" / key
                if not music_output_dir.exists():
                    with cluster.prefix(prefix_str):
                        wrappers.music(
                            cluster=cluster,
                            music_params=music_params,
                            output_dir=music_output_dir,
                        )

            with ch_time_block.ctx("enzo preface"):
                # These are the files that MUSIC creates.
                generated_enzo_params = enzo_parse_params((music_output_dir / "parameter_file.txt").read_text())
                enzo_paths = [
                    music_output_dir / cast(str, generated_enzo_params[f"CosmologySimulationParticle{quantity}{n}Name"])
                    for quantity in ["Velocity", "Displacement"]
                    for n in range(1, 4)
                ]

                # Combine generated Enzo params with override params
                override_enzo_params = yaml.safe_load((script_dir / "params/enzo.yaml").read_text())
                enzo_params: Mapping[str, EnzoValueType] = {
                    **generated_enzo_params,
                    **override_enzo_params,
                    "MaximumRefinementLevel": grid_depth,
                    "MaximumGravityRefinementLevel": grid_depth,
                    "MaximumParticleRefinementLevel": grid_depth,
                    "dtDataDump": dt_data_dump if cosmology_animation else 0,
                    "CosmologyOutputRedshift[10]": 0.0,
                }

                # Run Enzo if the data does not already exist for this config.
                key = "{:016x}".format(determ_hash(freeze(enzo_params)))
                enzo_output_dir = data_dir / "enzo" / key
                if not enzo_output_dir.exists():
                    # Copy initial conditions over.
                    enzo_output_dir.mkdir(parents=True)
                    for path in enzo_paths:
                        (enzo_output_dir / path.name).symlink_to(path)
                    with cluster.prefix(prefix_str):
                        wrappers.enzo(
                            cluster=cluster,
                            enzo_params=enzo_params,
                            output_dir=enzo_output_dir,
                            ntasks=max(1, (2 ** grid_depth) ** 3 // enzo_boxes_per_task),
                            slurm_partition=slurm_partition,
                            zstart=zstart,
                            key=key
                    )

            with ch_time_block.ctx("process_data preface"):
                # Run process_data.py on the data.
                process_data_script = script_dir / "process_data.py"
                key = "{:016x}".format(determ_hash(freeze(enzo_params)) ^ determ_hash(process_data_script.read_text()))
                processed_data_path = data_dir / "processed" / key
                FabricPath.copy(process_data_script, data_dir / "process_data.py")
                with ch_time_block.ctx("process_data"), cluster.prefix(prefix_str):
                    cluster.run(f"python {data_dir!s}/process_data.py {enzo_output_dir} {processed_data_path} {voxels_per_side} {padding} {int(cosmology_animation)}")
                data[grid_depth] = processed_data_path

        map2map_dir = data_dir / "map2map"
        if not map2map_dir.exists():
            cluster.run("git clone https://github.com/eelregit/map2map.git {map2map_dir!s}")

        with ch_time_block.ctx("map2map"):

            map2map_params = {
                "train-in-patterns": f"{data[grid_depths[0]]}/*.npy",
                "train-tgt-patterns": f"{data[grid_depths[1]]}/*.npy",
                "pad": 0,
                "scale-factor": 1,
                "model": "G",
                "adv-model": "D",
                "cgan": True,
                "percentile": 1,
                "adv-rw-reg-interval": 16,
                "lr": 5e-5,
                "adv-lr": 1e-5,
                "batches": 1,
                "loader-workers": 4,
                "epochs": 5,
                "seed": 42,
                "adv-start": 1,
                "incr-adv-lr": 1,
                "randnumber": random.randint(0, 9999),
                "optimizer-args": '{\\"betas\\": [0., 0.9], \\"weight_decay\\": 1e-4}',
                "optimizer": "AdamW",
                "augment": True,
            }
            map2map_params_str = " ".join([
                "--{key} {str(val) if val != True else ''}".strip()
                for key, val in map2map_params.items()
            ])
            cluster.run(f"python {map2map_dir!s}/m2m.py {map2map_params_str}")
            
            with ch_time_block.ctx("copy_tree"):
                FabricPath.copytree(processed_data_path, script_dir / "processed" / key)


if __name__ == "__main__":
    main()
