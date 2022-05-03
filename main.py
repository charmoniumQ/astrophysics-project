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
    zstart: int = 128,
    resolutions: Mapping[str, int] = {"low": 4, "high": 6},
    enzo_boxes_per_task: int = 64 ** 3,
    cluster: invoke.Runner = fabric.Connection("cluster"),
    data_dir: Path = Path("/scratch/users/grayson5/data"),
    spack_dir: Path = Path("/scratch/users/grayson5/spack"),
    spack_env: str = "main4",
    conda_env: str = "main3",
    slurm_partition: str = "eng-instruction",
    voxels_per_side: int = 64,
    padding: int = 24,
    dt_data_dump: int = 5,
    plot_cosmology: bool = True,
    do_eval: bool = False,
) -> None:

    script_dir = Path(__file__).parent

    random.seed(0)

    spack_prefix = f"source {spack_dir!s}/share/spack/setup-env.sh && spack env activate {spack_env}"
    with cluster:
        data_dir = FabricPath(data_dir, cluster).cast()

        # Combine MUSIC params with override params.
        music_params = yaml.safe_load(
            ((script_dir / "params/music.yaml").read_text())
        )
        music_params["setup"]["zstart"] = zstart
        music_params["setup"]["levelmin"] = resolutions["high"]
        music_params["setup"]["levelmax"] = resolutions["high"]
        for level in range(resolutions["high"]):
            music_params["random"][f"seed[level]"] = random.randint(0, 9999)

        # Run MUSIC if data does not already exist for this config.
        key = "{:016x}".format(determ_hash(freeze(music_params)))
        music_output_dir = data_dir / "music" / key
        if not music_output_dir.exists():
            with cluster.prefix(spack_prefix):
                wrappers.music(
                    cluster=cluster,
                    music_params=music_params,
                    output_dir=music_output_dir,
                )

        # These are the files that MUSIC creates.
        generated_enzo_params, enzo_paths = music_get_stored_output(
            music_output_dir
        )
        override_enzo_params = yaml.safe_load(
            (script_dir / "params/enzo.yaml").read_text()
        )

        for (resolution_str, resolution), is_train in itertools.product(
            resolutions.items(), ([True, False] if do_eval else [True])
        ):

            # Combine generated Enzo params with override params
            cosmology_animation = is_train and resolution_str == "high"
            if cosmology_animation:
                print("Doing cosmology animation")
            enzo_params: dict[str, EnzoValueType] = {
                **generated_enzo_params,
                **override_enzo_params,
                "TopGridDimensions": " ".join(map(str, 3 * (2**resolution,))),
                "MaximumRefinementLevel": resolution,
                "MaximumGravityRefinementLevel": resolution,
                "MaximumParticleRefinementLevel": resolution,
                "CosmologyOutputRedshift[10]": 0.0,
                "dtDataDump": dt_data_dump if cosmology_animation else 0,
            }

            # Run Enzo if the data does not already exist for this config.
            key = "{:016x}".format(
                determ_hash(freeze(music_params)) ^ determ_hash(freeze(enzo_params))
            )
            # This shouldn't affect the hash
            enzo_output_dir = data_dir / "enzo" / key
            if not enzo_output_dir.exists():
                # Copy initial conditions over.
                enzo_output_dir.mkdir(parents=True)
                for path in enzo_paths:
                    (enzo_output_dir / path.name).symlink_to(path)
                with cluster.prefix(spack_prefix):
                    wrappers.enzo(
                        cluster=cluster,
                        enzo_params=enzo_params,
                        output_dir=enzo_output_dir,
                        ntasks=max(
                            1, (2 ** resolution) ** 3 // enzo_boxes_per_task
                        ),
                        slurm_partition=slurm_partition,
                        zstart=zstart,
                        key=key,
                    )
            print(("train" if is_train else "test"), resolution_str, resolution, enzo_output_dir)
            nn_class_data_dir = (
                data_dir / "nn" / ("train" if is_train else "test") / resolution_str
            )
            nn_class_data_dir.mkdir(parents=True, exist_ok=True)
            if (nn_class_data_dir / "raw").exists() and (
                nn_class_data_dir / "raw"
            ).readlink() != enzo_output_dir:
                (nn_class_data_dir / "raw").unlink()
            if not (nn_class_data_dir / "raw").exists():
                (nn_class_data_dir / "raw").symlink_to(enzo_output_dir)

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
                            data_dir / "nn",
                            voxels_per_side,
                            padding,
                        ],
                    )
                ),
            )
        cosmology_dir = script_dir / "cosmology"
        if not cosmology_dir.exists():
            cosmology_dir.mkdir(exist_ok=True)
            FabricPath.copytree(
                data_dir / "nn/train/high/cosmology/", cosmology_dir
            )

        map2map_dir = data_dir / "map2map"

        map2map_params = {
            "train-in-patterns": f"{data_dir!s}/nn/train/low/chopped/*.npy",
            "train-tgt-patterns": f"{data_dir!s}/nn/train/high/chopped/*.npy",
            "model": "G",
            "adv-model": "D",
            "cgan": True,
            "percentile": 1,
            # "adv-rl-reg-interval": 16,
            # "lr": 5e-5,
            # "adv-lr": 1e-5,
            "batches": 1,
            "loader-workers": 4,
            "epochs": 5,
            "seed": 42,
            "adv-start": 1,
            # "incr-adv-lr": 1,
            # "randnumber": random.randint(0, 9999),
            "optimizer-args": '{\\"betas\\": [0., 0.9], \\"weight_decay\\": 1e-4}',
            "optimizer": "AdamW",
            "augment": True,
        }
        with ch_time_block.ctx("map2map"):
            pass
            # map2map(cluster, conda_env, map2map_params)


if __name__ == "__main__":
    main()
