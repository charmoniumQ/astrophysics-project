- Tool that I didn't write: Spack
  - Spack is a package manager for HPC systems.
  - Automate pulling down and building dependencies.
  - Lockfile => deterministic set of sources
    - Can still parameterize the build or change the compiler.
    - Easily reproduce my paper.
  - Found Enzo.
    - Here's how to install (if time).
  - Wrote package for MUSIC.
    - Accepted into mainline.

- Tool that I wrote before this class: charmonium.cache
  - Caches Python function.
  - Function granularity vs file granularity
    - Not havin to write CLI.

- Tool that I wrote specifically for this class: slurmpy-highlevel
  - Python interface to Slurm
    - Don't have to learn command line options.
    - Don't have to SSH.
    - Can use Python types (e.g. timedelta).
      - Submit _with tenacity_.

- Fix Enzo's documentation.
