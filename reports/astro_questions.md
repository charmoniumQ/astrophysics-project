- What share of your (percantage) time did you spend on downloading, compiling, and installing the dependencies of your program?
- What share of your (percantage) time did you spend on downloading, compiling, and installing your program?
- Would you be interested in using a tool that automates the process of installing programs and their dependencies?
- On a scale from 1 to 5, was Slurm over SSH very easy (1) or very frustrating (5) to use?

- Would you be interested in a Python library that automates the submission of Surm jobs? You would write something like and run it on your machine:
```
    # Specify the cluster
    campus_cluster = Connection("grayson5@cc-login.campuscluster.illinois.edu")

    # Specify the job
    job = SlurmJob.submit(
        "mpirun ./FLASH4",
        runner=campus_cluster,
        ntasks=8,
		cpus_per_task=4,
        ... # other options here
    )

    # Wait for it to finish
    await job.run_to_completion()
```
- What other technical obstacles or nuisances did you encounter?
- Is your workflow reproducible from your manuscript?
