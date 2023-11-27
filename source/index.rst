.. Snakemake plugin catalog documentation master file, created by
   sphinx-quickstart on Mon Oct  9 20:46:08 2023.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Snakemake plugin catalog
========================

This catalog collects information about and documentation of all Snakemake plugins
published on `PyPI <https://pypi.org/>`_.

.. toctree::
   :hidden:
   :caption: executor plugins

   cluster-generic <plugins/executor/cluster-generic>
   cluster-sync <plugins/executor/cluster-sync>
   drmaa <plugins/executor/drmaa>
   kubernetes <plugins/executor/kubernetes>
   slurm <plugins/executor/slurm>
   slurm-jobstep <plugins/executor/slurm-jobstep>
   tes <plugins/executor/tes>
.. toctree::
   :hidden:
   :caption: storage plugins

   fs <plugins/storage/fs>
   http <plugins/storage/http>
   s3 <plugins/storage/s3>
   sftp <plugins/storage/sftp>
