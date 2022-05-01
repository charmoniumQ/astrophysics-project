from pathlib import Path
import yt


def main(data: Path) -> None:
    ds = yt.load(data)
    mass = ds.fields.all.particle_mass
    # all_data_level_0 = ds.covering_grid(
    #     level=0, left_edge=[0, 0.0, 0.0], dims=ds.domain_dimensions
    # )

    # region = ds.r[(20, "m"):(30, "m"), (30, "m"):(40, "m"), (7, "m"):(17, "m")]

if __name__ == "__main__":
    import sys
    data = Path(sys.argv[1])
    main(data)
