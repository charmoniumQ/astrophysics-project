import itertools
import yt
from pathlib import Path

# Begin parameters

# sim box size in Mpc/h'
simsize = 75

# number of voxels per dimension the sim gets divided into
pixside = 2048

# padding pixels at each side per dimension
pad = 24

# size of individual (unpadded) training cube
crop = 64

# maximum cubesize such that window interpolation still works due to int not long_int being used in mpi4py
maxsize = 1024

ndim = 3

output_path = Path("/scratch/grayson5")

# End parameters

def crops(fields, anchor, crop, pad, size):
    """
    Adapted from Yin Li's map2map code.
    """
    ndim = len(size)
    assert all(len(x) == ndim for x in [anchor, crop, pad, size]), 'inconsistent ndim'
    new_fields = np.zeros((ndim, fields.shape[1]))
    for ix, x in enumerate(fields): #loop over channel dim
        ind = tuple(
            (np.arange(a - p0, a + c + p1) % s).reshape((-1,) + (1,) * (ndim - d - 1))
            for d, (a, c, (p0, p1), s) in enumerate(zip(anchor, crop, pad, size))
        )
        new_fields[ix] = x[tuple(ind)]
    return np.array(new_fields)

size = tuple(maxsize + 2 * pad for _ in range(ndim))
field = np.zeros((1, *size))
for anchor in itertools.product(range(pad, maxsize + pad, crop), repeat=3):
    cropped = crops(field, anchor, (crop,) * ndim, ((pad,) * 2) * ndim, size)
    anchor_path = cube_path / "cube_{anchor[0] - pad}_{anchor[1] - pad}_{anchor[2] - pad}.npy"
    np.save(anchor_path, cropped)
