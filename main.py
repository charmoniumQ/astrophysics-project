#!/usr/bin/env python

from __future__ import annotations

import asyncio
import itertools
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
import fabric  # type: ignore
import invoke  # type: ignore
import yaml
from charmonium.determ_hash import determ_hash
from charmonium.freeze import freeze
from tqdm import tqdm

import wrappers
from util.fabric_pathlib import FabricPath
from util.highlevel_slurm import SlurmJob
from util.util import subprocess_run
from wrappers.enzo import ValueType as EnzoValueType
from wrappers.music import get_stored_output as music_get_stored_output


@ch_time_block.decor()
def main(
    zstart: int = 32,
    resolutions: Mapping[str, int] = {"low": 5, "high": 6},
    enzo_boxes_per_task: int = 64 ** 3,
    cluster: invoke.Runner = fabric.Connection("cluster"),
    data_dir: Path = Path("/scratch/users/grayson5/data"),
    spack_dir: Path = Path("/scratch/users/grayson5/spack"),
    spack_env: str = "main4",
    conda_env: str = "main3",
    slurm_partition: str = "eng-instruction",
    voxels_per_side: int = 32,
    padding: int = 12,
    dt_data_dump: int = 0,
    plot_cosmology: bool = True,
    redshift_data_dumps: int = 4,
) -> None:

    script_dir = Path(__file__).parent

    random.seed(0)

    spack_prefix = f"source {spack_dir!s}/share/spack/setup-env.sh && spack env activate {spack_env}"
    with cluster:
        data_dir = FabricPath(data_dir, cluster).cast()

        output_dir = data_dir / "output"

        # Combine MUSIC params with override params.
        music_params = yaml.safe_load(
            ((script_dir / "params/music.yaml").read_text())
        )
        music_params["setup"]["zstart"] = zstart
        music_params["setup"]["levelmin"] = resolutions["high"]
        music_params["setup"]["levelmax"] = resolutions["high"]
        for level in range(1, 1 + resolutions["high"]):
            music_params["random"][f"seed[level]"] = random.randint(0, 9999)

        # Run MUSIC if data does not already exist for this config.
        music_output_dir = data_dir / "music" / "{:016x}".format(determ_hash(freeze(music_params)))
        if not music_output_dir.exists():
            with cluster.prefix(spack_prefix):
                wrappers.music(
                    cluster=cluster,
                    music_params=music_params,
                    output_dir=music_output_dir,
                )

        # These are the files that MUSIC creates.
        generated_enzo_params, enzo_paths = music_get_stored_output(music_output_dir)
        override_enzo_params = yaml.safe_load((script_dir / "params/enzo.yaml").read_text())
        enzo_params: Mapping[str, EnzoValueType] = {
            **generated_enzo_params,
            **override_enzo_params,
            **{
                f"CosmologyOutputRedshift[{i + 1}]": zstart / 2**i
                for i in range(redshift_data_dumps - 1)
            },
            f"CosmologyOutputRedshift[{redshift_data_dumps}]": 0.0,
            "dtDataDump": dt_data_dump,
        }

        nn_key = "{:016x}".format(determ_hash(freeze((enzo_params, resolutions))))
        nn_data_dir = data_dir / "nn" / nn_key

        for (resolution_str, resolution), is_train in itertools.product(
            resolutions.items(), [True, False]
        ):

            # Combine generated Enzo params with override params
            resolution_enzo_params = {
                **enzo_params,
                "TopGridDimensions": " ".join(map(str, 3 * (2**resolution,))),
                "MaximumRefinementLevel": resolution,
                "MaximumGravityRefinementLevel": resolution,
                "MaximumParticleRefinementLevel": resolution,
            }

            # Run Enzo if the data does not already exist for this config.
            enzo_key = "{:016x}".format(
                determ_hash(freeze(resolution_enzo_params))
            )
            enzo_output_dir = data_dir / "enzo" / enzo_key
            if not enzo_output_dir.exists():
                # Copy initial conditions over.
                enzo_output_dir.mkdir(parents=True)
                for path in enzo_paths:
                    (enzo_output_dir / path.name).symlink_to(path)
                with cluster.prefix(spack_prefix):
                    wrappers.enzo(
                        cluster=cluster,
                        enzo_params=resolution_enzo_params,
                        output_dir=enzo_output_dir,
                        ntasks=max(
                            1, (2 ** resolution) ** 3 // enzo_boxes_per_task
                        ),
                        slurm_partition=slurm_partition,
                        zstart=zstart,
                        key=enzo_key,
                    )
            nn_class_data_dir = (
                nn_data_dir / ("train" if is_train else "test") / resolution_str
            )
            nn_class_data_dir.mkdir(parents=True, exist_ok=True)
            print(("train" if is_train else "test"), resolution_str, resolution, enzo_output_dir, nn_class_data_dir)
            raw_dir = (nn_class_data_dir / "raw")
            if raw_dir.exists():
                raw_dir.unlink()
            raw_dir.symlink_to(enzo_output_dir)

        # Run chop_data.py on the data.
        chop_data_script = data_dir / "chop_data.py"
        FabricPath.copy(script_dir / "chop_data.py", chop_data_script)
        with ch_time_block.ctx("chop_data"):
            cluster.run(
                " ".join(
                    map(
                        str,
                        [
                            "conda",
                            "run",
                            "--name",
                            conda_env,
                            "--no-capture-output",
                            "python",
                            chop_data_script,
                            nn_data_dir,
                            voxels_per_side,
                            padding,
                        ],
                    )
                ),
            )

        map2map_dir = data_dir / "map2map"

        default_map2map_params = yaml.safe_load((script_dir / "params/map2map.yaml").read_text())
        map2map_params = {
            "train-in-patterns": f"{data_dir!s}/nn/train/low/chopped/*.npy",
            "train-tgt-patterns": f"{data_dir!s}/nn/train/high/chopped/*.npy",
            **default_map2map_params,
        }
        with ch_time_block.ctx("map2map"):
            pass
            # map2map(cluster, conda_env, map2map_params)

        join_data_script = data_dir / "join_data.py"
        FabricPath.copy(script_dir / "join_data.py", join_data_script)
        with ch_time_block.ctx("join_data"):
            cluster.run(
                " ".join(
                    map(
                        str,
                        [
                            "conda",
                            "run",
                            "--name",
                            conda_env,
                            "--no-capture-output",
                            "python",
                            join_data_script,
                            nn_data_dir / f"test/low/raw/RD{redshift_data_dumps:04d}/RedshiftOutput{redshift_data_dumps:04d}",
                            nn_data_dir / "test/low/chopped",
                            nn_data_dir / "test/low/chopped",
                            nn_data_dir / "test/high/chopped",
                            output_dir,
                            padding,
                        ],
                    )
                ),
            )

        (output_dir / "high").mkdir(exist_ok=True)
        (output_dir / "low").mkdir(exist_ok=True)
        FabricPath.copytree(nn_data_dir / "test/high/plots", output_dir / "high")
        FabricPath.copytree(nn_data_dir / "test/low/plots", output_dir / "low")
        FabricPath.copytree(output_dir, script_dir / "output")

if __name__ == "__main__":
    main()
