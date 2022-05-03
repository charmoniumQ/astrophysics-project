from __future__ import annotations

import datetime
import itertools
import os
import re
import shutil
import stat
from pathlib import Path
from typing import Any, Iterable

import dask.bag  # type: ignore
import dask.diagnostics  # type: ignore
import yt  # type: ignore
from tqdm import tqdm


def consume(x: Iterable[Any]) -> None:
    for _ in x:
        pass


dm_field = ("deposit", "all_cic")


def mtime(path: Path) -> datetime.datetime:
    return datetime.datetime.fromtimestamp(os.stat(path)[stat.ST_MTIME])


def plot_cosmology(data_dir: Path, output_dir: Path) -> None:
    import matplotlib.animation  # type: ignore

    try:
        ts = yt.load(str(data_dir / "DD????/data????"))
    except FileNotFoundError:
        print("None found for", str(data_dir / "DD????/data????"))
        return
    if len(ts) > 0:
        for i, ds in enumerate(ts):
            plot = (
                yt.ProjectionPlot(ds, axis="z", fields=dm_field, method="integrate",)
                .annotate_timestamp(corner="upper_left", redshift=True, draw_inset_box=True)
                .annotate_scale(corner="upper_right")
                .set_log(dm_field, True, symlog_auto=True)
                .save(output_dir / f"projection_{i:04d}.png")
            )
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
    data_dir: Path, output_dir: Path, voxels_per_side: int, padding: int
) -> None:
    import numpy

    ds = yt.load(data_dir)
    dx = ds.index.get_smallest_dx()
    assert ds.domain_dimensions[0] == ds.domain_dimensions[1] == ds.domain_dimensions[2]
    domain_length = ds.refine_by ** ds.index.max_level
    box_dims = (padding * 2 + voxels_per_side,) * 3
    dask.bag.from_sequence(
        enumerate(
            itertools.product(
                range(padding, domain_length - padding, voxels_per_side), repeat=3
            )
        )
    ).starmap(
        lambda i, box_start: numpy.save(  # type: ignore
            output_dir / f"dm_{i:05d}.npy",
            ds.covering_grid(
                level=ds.index.max_level,
                left_edge=numpy.array(box_start) * dx,
                dims=box_dims,
                fields=[dm_field],
            )[dm_field],
        )
    ).compute()


def chop_nn_class_dir(
    nn_class_data_dir: Path, voxels_per_side: int, padding: int
) -> None:
    raw_dir = nn_class_data_dir / "raw"
    cosmology_dir = nn_class_data_dir / "cosmology"
    chopped_dir = nn_class_data_dir / "chopped"

    if cosmology_dir.exists() and mtime(raw_dir) > mtime(cosmology_dir):
        shutil.rmtree(cosmology_dir)
    if not cosmology_dir.exists():
        cosmology_dir.mkdir()
        print("going on plotting")
        plot_cosmology(raw_dir, cosmology_dir)

    if chopped_dir.exists() and  mtime(raw_dir) > mtime(chopped_dir):
        shutil.rmtree(chopped_dir)
    if not chopped_dir.exists():
        print("going on chopping")
        chopped_dir.mkdir()
        chop_frame(
            raw_dir / "RD0001/ReshiftOutput0001", chopped_dir, voxels_per_side, padding
        )


if __name__ == "__main__":
    import sys

    nn_data_dir = Path(sys.argv[1])
    voxels_per_side = int(sys.argv[2])
    padding = int(sys.argv[3])
    yt.set_log_level("warning")
    print(f"main({nn_data_dir}, {voxels_per_side}, {padding})")
    with dask.diagnostics.ProgressBar():
        paths = [
            nn_data_dir / "train/high",
        ]
        
        dask.bag.from_sequence(paths).map(
            chop_nn_class_dir, voxels_per_side=voxels_per_side, padding=padding
        ).compute()
