from __future__ import annotations

import datetime
import itertools
import os
import re
import shutil
import stat
from pathlib import Path
from typing import Any, Iterable, Sequence

import charmonium.time_block
import dask.bag
import dask.diagnostics
import yt  # type: ignore
from tqdm import tqdm


def consume(x: Iterable[Any]) -> None:
    for _ in x:
        pass


dm_field = ("deposit", "all_cic")


def mtime(path: Path) -> datetime.datetime:
    return datetime.datetime.fromtimestamp(os.stat(path)[stat.ST_MTIME])


def plot_cosmology_frame(ds: yt.Dataset, output_path: Path) -> None:
    (
        yt.ProjectionPlot(ds, axis="z", fields=dm_field, method="integrate",)
        .annotate_timestamp(corner="upper_left", redshift=True, draw_inset_box=True)
        .annotate_scale(corner="upper_right")
        .set_log(dm_field, True, symlog_auto=True)
        .save(output_path)
    )


def plot_cosmology(dss: Sequence[yt.Dataset], output_dir: Path) -> None:
    for i, ds in enumerate(dss):
        plot_cosmology_frame(ds, output_dir / f"projection_{i:04d}.pdf")
    # import matplotlib.animation  # type: ignore
    # plot = (
    #     yt.ProjectionPlot(ts[0], axis="z", fields=dm_field, method="integrate",)
    #     .annotate_timestamp(corner="upper_left", redshift=True, draw_inset_box=True)
    #     .annotate_scale(corner="upper_right")
    #     .set_log(dm_field, True, symlog_auto=True)
    # )
    # animation = matplotlib.animation.FuncAnimation(
    #     plot.plots[dm_field].figure,
    #     lambda i: plot._switch_ds(ts[3 * i]),
    #     frames=len(ts) // 3,
    #     interval=1000,
    # )
    # animation.save("projection.gif")
    # print("hi", len(ts))
    # animation.save("projection_%04d.png")


def chop_frame(
        ds: yt.Dataset, output_dir: Path, voxels_per_side: int, padding: int, is_train: bool
) -> None:
    import numpy

    dx = ds.index.get_smallest_dx()
    assert ds.domain_dimensions[0] == ds.domain_dimensions[1] == ds.domain_dimensions[2]
    domain_length_voxels = ds.domain_dimensions[0] * ds.refine_by ** ds.index.max_level
    block_length_voxels = (voxels_per_side + (padding * 2 if is_train else 0),) * 3
    domain_length_blocks = domain_length_voxels // voxels_per_side - 2 * padding
    print(f"{ds.refine_by} ** {ds.index.max_level} = {domain_length_voxels} = {domain_length_blocks} * {block_length_voxels}")
    block_idxs = itertools.product(range(domain_length_blocks), repeat=3)
    for i, j, k in tqdm(block_idxs, total=domain_length_blocks**3):
        grid = ds.covering_grid(
            level=ds.index.max_level,
            left_edge=(numpy.array([i, j, k]) * voxels_per_side + (0 if is_train else padding)) * dx,
            dims=block_length_voxels,
            fields=[dm_field],
        )
        numpy.save(output_dir / f"dm_{i:04d}_{j:04d}_{k:04d}.npy", grid[dm_field])

    # dask.bag.from_sequence( # type: ignore
    #     indexes,
    # ).starmap(
    #     lambda i, j, k: numpy.save(
    #         output_dir / f"dm_{i:04d}_{j:04d}_{k:04d}.npy",
    #         ds.covering_grid(
    #             level=ds.index.max_level,
    #             left_edge=(np.array([i, j, k]) * voxels_per_side + (0 if is_train else padding)) * dx,
    #             dims=block_length,
    #             fields=[dm_field],
    #         )[dm_field],
    #     )
    # ).compute()


def chop_nn_class_dir(
    nn_class_data_dir: Path, voxels_per_side: int, padding: int, is_train: bool
) -> None:
    raw_dir = nn_class_data_dir / "raw"
    plots_dir = nn_class_data_dir / "plots"
    chopped_dir = nn_class_data_dir / "chopped"

    with charmonium.time_block.ctx("Load data"):
        if not plots_dir.exists() or not chopped_dir.exists():
            dss = yt.load(str(raw_dir / "RD????/RedshiftOutput????"))

    with charmonium.time_block.ctx("Plotting"):
        if not plots_dir.exists():
            plots_dir.mkdir()
            # yt.load(str(raw_dir / "DD????/data????"))
            plot_cosmology(dss, plots_dir)

    with charmonium.time_block.ctx("Chopping"):
        if not chopped_dir.exists():
            print("chopping")
            chopped_dir.mkdir()
            try:
                chop_frame(
                    dss[-1], chopped_dir, voxels_per_side, padding, is_train
                )
            except Exception as e:
                shutil.rmtree(chopped_dir)
                raise e


if __name__ == "__main__":
    import sys

    nn_data_dir = Path(sys.argv[1])
    voxels_per_side = int(sys.argv[2])
    padding = int(sys.argv[3])
    yt.set_log_level("warning")
    print(f"main({nn_data_dir}, {voxels_per_side}, {padding})")
    paths = [
        (nn_data_dir / "train/high", False),
        (nn_data_dir / "train/low", True),
        (nn_data_dir / "test/low", True),
    ]
    with dask.diagnostics.ProgressBar(): # type: ignore
        for path, is_train in paths:
            print(path, is_train, voxels_per_side, padding)
            chop_nn_class_dir(path, voxels_per_side, padding, is_train)
