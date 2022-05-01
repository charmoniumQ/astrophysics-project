# Using Spack on the Campus Cluster

- 

- It is quite easy for Spack packages to surpass the 5GiB quota on one's home directory. Consider adding `install_tree` in `~/.spack/config.yaml` to `/scratch/users/$user/opt` (non-persistent) or `/project/$PROJECT/opt` (persistent).

  ```yaml
  config:
    install_tree: /scratch/users/$user/opt
     # other stuff here
  ```

- The default gcc is quite old (`4.8.5`). Consider adding a `gcc/7.2.0` from the `module` system to your `~/.spack/linux/compilers.yaml`:

  ```yaml
  compiler:
  - compiler:
      spec: gcc@7.2.0
      paths:
        cc: /usr/local/gcc/7.2.0/bin/gcc
        cxx: /usr/local/gcc/7.2.0/bin/g++
        f77: /usr/local/gcc/7.2.0/bin/gfortran
        fc: /usr/local/gcc/7.2.0/bin/gfortran
      flags: {}
      operating_system: rhel7
      target: x86_64
      modules: [gcc/7.2.0]
      extra_rpaths: []
  # other stuff here
  ```

- Alternatively, you can try installing a new compiler `srun --ntasks=8 --time=01:00:00 --partition=$PARTITION --pty spack install gcc@11.2`, which will automatically add the new compiler to your `~/.spack/linux/compilers.yaml`. I'm not sure how Spack decides what compiler to use; you may have to add `%gcc@7.2.0` to force Spack to use the newer `gcc`.

- Runing `spack install` on the head node will likely take too long and get your process killed. Environment commands such as `spack env activate`, `spack add`, and `spack concretize` should be fine.

    ```shell
    $ # If you will be logged in the whole time, use an interactive session.
	$ srun --ntasks=8 --time=01:00:00 --partition=$PARTITION --pty spack install

    $ # If you want to log out and log back in while Spack is installing, use sbatch.
	$ sbatch --ntasks=8 --time=01:00:00 --partition=$PARTITION --stdout=stdout --wrap='spack install'
    $ # When you log back in, use tail to follow the output (live updates). Press Ctrl+C to exit tail.
    $ tail --follow stdout
	```

- Note that I had to write `concretize: together` to prevent `fatal error(s) when merging prefixes`.

  ```yaml
  spack:
    concretization: together
    # other stuff
  ```
