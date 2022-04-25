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
from typing import Generator, Mapping, Union
import yaml

import charmonium.time_block as ch_time_block
from util.fabric_pathlib import FabricPath
from util.highlevel_slurm import SlurmJob
from tqdm import tqdm
import fabric  # type: ignore

from util.util import subprocess_run
import wrappers

@ch_time_block.decor()
def main2(
        zstart: int = 63,
        music_levels: int = 5,
        enzo_boxes_per_task: int = 64 ** 3,
        cluster_host: str = "cluster",
        bin_dir_loc: Path = Path("/home/grayson5/project/remote_code/.spack-env/view/bin"),
        data_dir_loc: Path = Path("/home/grayson5/data"),
        slurm_partition: str = "eng-instruction",
) -> None:

    ntasks = max(1, (2 ** music_levels) ** 3 // enzo_boxes_per_task)

    script_dir = Path(__file__).parent

    with fabric.Connection(cluster_host) as cluster:
        bin_dir = FabricPath(cluster, bin_dir_loc).cast()
        data_dir = FabricPath(cluster, data_dir_loc).cast()

        music_params = yaml.safe_load(((script_dir / "params/music.yaml").read_text()))

        music_params["setup"]["zstart"] = zstart
        music_params["setup"]["levelmin"] = music_levels
        music_params["setup"]["levelmax"] = music_levels

        generated_enzo_params = wrappers.music(
            cluster,
            bin_dir,
            music_params,
            data_dir,
        )

        enzo_params = {
            **generated_enzo_params,
            **yaml.safe_load((script_dir / "params/enzo.yaml").read_text()),
        }

        wrappers.enzo(
            cluster,
            bin_dir,
            enzo_params,
            data_dir,
            ntasks,
            slurm_partition,
            zstart,
        )


if __name__ == "__main__":
    main2()
