# jpit (v4.6.3, frozen)

[Code signing policy](https://github.com/Burkhardt/RAIkeep/blob/main/README_codesigning.md)

This is the frozen `jpit` companion for the historical
[`jsonpit-python`](https://github.com/Burkhardt/jsonpit-python) project. Active
Python development continues in [`umgodi-json`](https://github.com/Burkhardt/umgodi-json),
which keeps developing the `jpit` CLI and provides the `umgodi` import package.
The C# `JsonPit` implementation remains the heritage and cross-engine
reference; the Python successor is intentionally named `umgodi-json`.
Python 3.12 or newer is required.

## Installation

For a new CLI installation, use one pipx environment:

```bash
pipx install "jsonpit==4.6.3"
jpit --version
jsonpit --version
```

To upgrade, run `pipx upgrade jsonpit`. Both commands include the `v` prefix in
their version output, for example `jpit v4.6.3`. These installation commands
apply after publication.

If both distributions were installed into separate pipx environments:

```bash
pipx uninstall jpit
pipx install --force "jsonpit==4.6.3"
```

Use a virtual environment to embed the library in a Python application. Do not
bypass the operating system's externally managed Python protection.

For active development, use the [Umgodi Getting Started guide](https://github.com/Burkhardt/umgodi-json/blob/main/GettingStarted.md)
and [API reference](https://github.com/Burkhardt/umgodi-json/blob/main/API.md).
