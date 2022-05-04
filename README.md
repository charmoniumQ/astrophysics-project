# Neural Network Superresolving for Cosmological Simulations

In this repository, I attempt to reproduce the analysis of [Schaurecker et
al. 2021][1] on Enzo data (they use Illustris).

[1]: https://arxiv.org/pdf/2111.06393.pdf

# To reproduce

The code `main.py` is intended to be run locally. It sends commands to the
remote. You will need to modify this with your site-specific parameters. It
should be the only file you need to modify.

To set up the remote machine (should be capable of Slurm):

```sh
remote$ # Install Spack on the remote
remote$ git clone -c feature.manyFiles=true https://github.com/spack/spack.git

remote$ # Copy spack.lock to the remote
remote$ spack/bin/spack environment create main4 spack.lock
remote$ spack/bin/spack environment activate main4
remote$ spack/bin/spack concretize
remote$ spack/bin/spack install

remote$ # Copy envirment.yaml ot the remote
remote$ spack/bin/spack activate main4
remote$ conda install --name main3 --file environment,yaml

remote$ # Ensure that Slurm works
remote$ sbatch --help
```

To set up the local machine:

```sh
locla$ # Install conda
locla$ # Install conda environment
local$ conda install --name main3 --file environment,yaml
```

You will need to configure SSH keys to the remote.

Then you should be to run `main.py`. `main.py` runs the entire workflow. It is
smart about not running a certain step if the data already exists. It also
hashes the input parameters in the filename of the data, so it is unlikely to
return stale data.

The end result will end up in `output`.
