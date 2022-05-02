from __future__ import annotations
from typing import Iterable, Any
import shutil
from tqdm import tqdm
import itertools
import re
import numpy
import dask.bag  # type: ignore
import dask.diagnostics  # type: ignore
from pathlib import Path
import yt  # type: ignore


def consume(x: Iterable[Any]) -> None:
    for _ in x:
        pass


dm_field = ("deposit", "all_cic")
def plot_cosmology(data_path: Path, num: int) -> None:
    ds = None
    fname = output_dir / f"projection_{num:04d}.png"
    if not fname.exists():
        ds = yt.load(data_path) if ds is None else ds
        (
            yt.ProjectionPlot(
                ds,
                axis="z",
                fields=dm_field,
                method="integrate",
            )
            .annotate_timestamp(corner="upper_left", redshift=True, draw_inset_box=True)
            .annotate_scale(corner="upper_right")
            .set_log(dm_field, True, symlog_auto=True)
            .save(fname)
        )
    tqdm.write(f"{data_path!s}\n")

def split_frame(data_path: Path, num: int, voxels_per_side: int, padding: int) -> None:
    ds = yt.load(data_path)
    dx = ds.index.get_smallest_dx()
    assert ds.domain_dimensions[0] == ds.domain_dimensions[1] == ds.domain_dimensions[2]
    domain_length = ds.refine_by ** ds.index.max_level
    box_dims = (padding * 2 + voxels_per_side,) * 3
    dask.bag.from_sequence(
        enumerate(itertools.product(range(padding, domain_length - padding, voxels_per_side), repeat=3))
    ).map(lambda i_box_start: numpy.save(
        output_dir / f"field_{num:04d}_{i_box_start[0]:05d}.npy",
        ds.covering_grid(
            level=ds.index.max_level,
            left_edge=numpy.array(i_box_start[1]) * dx,
            dims=box_dims,
            fields=[dm_field],
        )
        [dm_field]
    )).compute()


def main(input_dir: Path, output_dir: Path, voxels_per_side: int, padding: int, should_plot_cosmology: bool) -> None:
    data_path_nums = []
    data_pattern = re.compile(r"DD(\d{4})")
    for path in input_dir.iterdir():
        match = data_pattern.match(path.name)
        if match:
            num = int(match.group(1))
            data_path_nums.append((path / f"data{num:04d}", num))
    yt.set_log_level("warning")
    if should_plot_cosmology:
        dask.bag.from_sequence(data_path_nums).map(plot_cosmology).compute()
    split_frame(Path("RD0001/ReshiftOutput0001"), 1, voxels_per_side, padding)


if __name__ == "__main__":
    import sys
    input_dir = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])
    voxels_per_side = int(sys.argv[3])
    padding = int(sys.argv[4])
    should_plot_cosmology = bool(int(sys.argv[5]))
    if not output_dir.exists():
        output_dir.mkdir(parents=True)
    print(f"main({input_dir}, {output_dir}, {voxels_per_side}, {padding}, {should_plot_cosmology})")
    with dask.diagnostics.ProgressBar():
        main(input_dir, output_dir, voxels_per_side, padding, should_plot_cosmology)

