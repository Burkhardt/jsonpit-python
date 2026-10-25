# jpit (v4.5.13)

`jpit` is the companion distribution for [jsonpit](https://pypi.org/project/jsonpit/).
It depends on the matching library version and exposes the `jpit` and `jsonpit` commands.
Python 3.12 or newer is required.

## Installation

For a new CLI installation, use one pipx environment:

```bash
pipx install "jsonpit==4.5.13"
jpit --version
jsonpit --version
```

To upgrade, run `pipx upgrade jsonpit`. Both commands include the `v` prefix in
their version output, for example `jpit v4.5.13`.

If both distributions were installed into separate pipx environments:

```bash
pipx uninstall jpit
pipx install --force "jsonpit==4.5.13"
```

Use a virtual environment to embed the library in a Python application. Do not
bypass the operating system's externally managed Python protection.

See the [Getting Started guide](https://github.com/Burkhardt/jsonpit-python/blob/main/GettingStarted.md)
and [API reference](https://github.com/Burkhardt/jsonpit-python/blob/main/API.md).
