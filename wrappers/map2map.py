from pathlib import Path
from typing import Mapping, Union

import invoke  # type: ignore

ValueType = Union[int, float, str, bool, Path]
ParamsType = Mapping[str, ValueType]

source_dir = Path("map2map")


def map2map(runner: invoke.Runner, conda_env: str, params: ParamsType) -> None:
    if not source_dir.exists():
        runner.run("git clone https://github.com/eelregit/map2map.git {source_dir!s}")
    params_str = " ".join(
        [
            "--{key} {str(val) if val != True else ''}".strip()
            for key, val in params.items()
        ]
    )
    runner.run(f"conda run --name {conda_env} --no-capture-output python {source_dir!s}/m2m.py {params_str}")
    # TOOD: use Slurm
