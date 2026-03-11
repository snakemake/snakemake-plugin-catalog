# snakemake-plugin-catalog

An automatically updated catalog of
[Snakemake plugins](https://snakemake.readthedocs.io/en/stable/project_info/codebase.html#plugins)
and their documentation. See
<https://snakemake.github.io/snakemake-plugin-catalog/> (generated from
[this template](/source/_templates/index.rst.j2)) for a general overview of the
catalog.

## Contributing

> WARNING: The `build` task is designed to run on a GitHub runner and will
> install essentially arbitrary code on the machine it is run on. Don't run it
> unless you understand the risk involved! The same goes for `build-specific` if
> you don't understand the plugin you run it on.

### Software environment

Like the rest of the Snakemake ecosystem, the plugin catalog uses
[Pixi](https://pixi.prefix.dev/latest/) to manage software environments and
common development and deployment tasks. See their docs for detailed information
on setup and task running.

### Development

After making changes to the code, ensure the code is consistently formatted by
doing `pixi run style`. If you make changes to the Jinja templates used to build
the catalog, ensure the underlying rst files follow the general Snakemake
[documentation guidelines](https://snakemake.readthedocs.io/en/stable/project_info/contributing.html#documentation-guidelines).

### Testing

Currently there are no unit-tests. Checking whether the code works as expected
is done by building individual plugin docs via the `build-specific` Pixi task.
