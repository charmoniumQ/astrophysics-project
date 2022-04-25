import os
from pathlib import Path
from typing import Mapping, Union

import charmonium.time_block as ch_time_block
import invoke  # type: ignore

from util.fabric_pathlib import FabricPath

from .enzo import ParamsType as EnzoParamsType
from .enzo import parse_params as enzo_parse_params

ValueType = Union[int, float, str, bool, Path]

ParamsType = Mapping[str, Mapping[str, ValueType]]


def format_music_value(value: ValueType) -> str:
    return {True: "yes", False: "no"}[value] if isinstance(value, bool) else str(value)


def format_music_params(music_params: ParamsType) -> str:
    return "\n".join(
        [
            "\n".join(
                [
                    f"[{section}]",
                    "\n".join(
                        [
                            f"{key} = {format_music_value(val)}"
                            for key, val in key_vals.items()
                        ]
                    ),
                    "",
                ]
            )
            for section, key_vals in music_params.items()
        ]
    )


@ch_time_block.decor()
def run_music(
        cluster: invoke.Runner, bin_dir: Path, output_dir: Path, data_dir: Path, music_param_file: Path,
) -> None:
    if data_dir.exists():
        FabricPath.rmtree(data_dir)

    with cluster.cd(str(output_dir)):
        nproc = int(cluster.run("nproc", hide="both").stdout)
        cluster.run(
            f"{bin_dir}/MUSIC {music_param_file!s}",
            env={"OMP_NUM_THREADS": str(nproc),},
            hide="both",
        )
def music(
    cluster: invoke.Runner, bin_dir: Path, music_params: ParamsType, output_dir: Path,
) -> EnzoParamsType:
    data_dir = output_dir / "data"
    enzo_param_file = data_dir / "parameter_file.txt"
    music_param_file = output_dir / "music_params.conf"
    music_params_str = format_music_params(
        {**music_params, "output": {"format": "enzo", "filename": data_dir,},}
    )

    if not enzo_param_file.exists() or music_params_str != music_param_file.read_text():
        music_param_file.write_text(music_params_str)
        run_music(cluster, bin_dir, output_dir, data_dir, music_param_file)

    return enzo_parse_params(enzo_param_file.read_text())
