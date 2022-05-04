from __future__ import annotations

import sys
from pathlib import Path
import itertools
import re
from tqdm import tqdm

import numpy
import yt  # type: ignore
from yt.extensions.astro_analysis.halo_analysis import HaloCatalog  # type: ignore


dm_field = ("deposit", "all_cic")
pattern = re.compile(r"[a-z]+_[0-9]+_[0-9]+_[0-9]+\.npy")
def reconstruct(base_ds: yt.Dataset, input_dir: Path, padding: int) -> yt.Dataset:
    paths: dict[tuple[int, ...], Path] = {}
    n_dims = 3
    for path in input_dir.glob("*.npy"):
        match = pattern.match(path.name)
        if match:
            block = numpy.load(path)
            paths[tuple(int(match.group(dim)) for dim in range(n_dims))] = path
    arr_length_in_blocks: numpy.typing.NDArray[numpy.float64] = numpy.array([
        max(paths.keys(), key=lambda coords: coords[dim])
        for dim in range(n_dims)
    ])
    assert numpy.product(arr_length_in_blocks) == len(paths.keys())
    block_length_in_pixels = numpy.load(paths[(0,) * n_dims]).shape - 2 * padding
    arr_length_in_pixels = arr_length_in_blocks * block_length_in_pixels
    arr = numpy.zeros(arr_length_in_pixels)
    for block_idx in tqdm(itertools.product(range(dim) for dim in arr_length_in_blocks)):
        arr[block_idx * block_length_in_pixels] = \
            numpy.load(paths[block_idx])[(slice(padding, -padding),) * n_dims]
    return yt.load_uniform_grid_data(
        {
            ("all", "density"): (arr, base_ds.fields[dm_field].units),
        },
        arr.shape,
        length_unit=base_ds.length_unit,
        bbox=numpy.dstack((
            numpy.min(numpy.min(base_ds.index.grid_corners, axis=0), axis=1),
            numpy.max(numpy.max(base_ds.index.grid_corners, axis=0), axis=1),
        ))[0],
        sim_time=base_ds.current_time,
        mass_unit=base_ds.mass_unit,
        time_unit=base_ds.time_unit,
    )

def generate_particle_field(ds: yt.Dataset, density_field: tuple[str, str], num_particles: int) -> yt.Dataset:
    arr = yt.fields[density_field]
    arr *= num_particles / arr.sum()
    intpart = numpy.floor(arr)
    fracpart = arr - intpart
    particle_count = intpart + (fracpart > numpy.random.rand(fracpart.shape)).astype(int)
    particles = particle_count.sum()
    indexes = list(itertools.product(range(arr.shape[0]), range(arr.shape[1]), range(arr.shape[2])))
    positions_x, positions_y, positions_z = numpy.array([
        [i, j, k]
        for i, j, k in indexes
        for _ in range(particle_count[i, j, k])
    ]).T + numpy.random.random((3, particle_count))
    return yt.load_uniform_grid_data(
        {
            ("all", "particle_position_x"): (arr, ds.fields[dm_field].units),
            ("all", "particle_position_y"): (arr, ds.fields[dm_field].units),
            ("all", "particle_position_z"): (arr, ds.fields[dm_field].units),
        },
        arr.shape,
        length_unit=ds.length_unit,
        bbox=numpy.dstack((
            numpy.min(numpy.min(ds.index.grid_corners, axis=0), axis=1),
            numpy.max(numpy.max(ds.index.grid_corners, axis=0), axis=1),
        ))[0],
        sim_time=ds.current_time,
        mass_unit=ds.mass_unit,
        time_unit=ds.time_unit,
    )


if __name__ == "__main__":
    base_ds_path = Path(sys.argv[1])
    low_res_dir = Path(sys.argv[2])
    predicted_high_res_dir = Path(sys.argv[3])
    high_res_dir = Path(sys.argv[4])
    output_path = Path(sys.argv[5])
    padding = int(sys.argv[6])

    data = [
        ("low res", low_res_dir, padding),
        ("predicted high res", predicted_high_res_dir, 0),
        ("high res", high_res_dir, 0),
    ]

    base_ds = yt.load(base_ds_path)
    for label, data_dir, padding in data:
        density_ds = reconstruct(base_ds, data_dir, padding)
        num_particles = density_ds.fields["all", "density"].r[:, :, :].max() * 100
        particle_ds = generate_particle_field(density_ds, ("all", "density"), num_particles)
        hc = HaloCatalog(data_ds=particle_ds, finder_method="fof")
        hc.create()
        (
            yt.ProjectionPlot(density_ds, axis="z", fields=("all", "density"), method="integrate",)
            .annotate_timestamp(corner="upper_left", redshift=True, draw_inset_box=True)
            .annotate_scale(corner="upper_right")
            .annotate_halos(hc)
            .set_log(dm_field, True, symlog_auto=True)
            .save(output_path / (label + "_halo.pdf"))
        )
