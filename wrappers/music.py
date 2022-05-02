import itertools
import os
from pathlib import Path
from typing import Mapping, Union, Sequence, cast

import charmonium.time_block as ch_time_block
import invoke  # type: ignore

from util.fabric_pathlib import FabricPath

from .enzo import (
    ParamsType as EnzoParamsType,
    parse_params as enzo_parse_params,
    format_params as enzo_format_params,
)

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
def music(
    cluster: invoke.Runner, music_params: ParamsType, output_dir: Path,
) -> tuple[EnzoParamsType, Sequence[Path]]:
    music_params = {
        **music_params,
        "output": {"format": "enzo", "filename": output_dir,},
    }

    run_dir = output_dir.parent / ".tmp"
    if run_dir.exists():
        FabricPath.rmtree(run_dir)
    run_dir.mkdir(parents=True)

    if output_dir.exists():
        FabricPath.rmtree(output_dir)

    music_param_file = run_dir / "music_params.conf"
    music_param_file.write_text(format_music_params(music_params))
    with cluster.cd(str(run_dir)):
        nproc = int(cluster.run("nproc", hide="stdout").stdout)
        cluster.run(
            f"MUSIC {music_param_file!s} > {run_dir!s}/music_stdout",
            env={"OMP_NUM_THREADS": str(nproc),},
            hide="stdout",
        )

    return get_stored_output(output_dir)


def get_stored_output(output_dir: Path) -> tuple[EnzoParamsType, Sequence[Path]]:
    generated_enzo_params = enzo_parse_params(
        (output_dir / "parameter_file.txt").read_text()
    )
    # Correct the values which refer to files (relative path ->  absolute path)
    enzo_paths = [
        output_dir
        / cast(
            str, generated_enzo_params[f"CosmologySimulationParticle{quantity}{n}Name"]
        )
        for quantity in ["Velocity", "Displacement"]
        for n in range(1, 4)
    ]
    return generated_enzo_params, enzo_paths
