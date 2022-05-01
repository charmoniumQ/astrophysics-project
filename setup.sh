#!/usr/bin/env bash

SPACK_DIR=${SPACK_DIR:-/scratch/users/$USER/spack}

SPACK_ENV=${SPACK_ENV:-main}

git clone https://github.com/spack/spack.git $SPACK_DIR

. $SPACK_DIR/share/spack/setup-env.sh

# spack env create main
# spack env activate --prompt main
# spack edit main
sbatch --time=01:30:00 --ntasks=8 \
     --partition=eng-instruction \
     --wrap='spack install'

# Put spack.lock on the remote

# Note this may not work due to issues related to a race condition in Spack
# https://github.com/spack/spack/issues/30291
# https://github.com/spack/spack/pull/18131#issuecomment-723016715
srun --time=01:30:00 --ntasks=8 \
     --partition=eng-instruction --pty \
     sh -c "spack env create ${SPACK_ENV} spack.lock && spack install"
