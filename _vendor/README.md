# Vendored dependencies

## Why anything is vendored at all

The engine's one hard dependency used to be a YAML parser, and `pip install` was the
first step of the install instructions. On a school machine that step fails in a dozen
ways — no `pip`, an externally-managed Python, a proxy, no network, a version conflict
with another project — and when it fails the engine cannot read a Design Spec at all.

A vendored pure-Python parser removes the step. Nothing to install, nothing to pin,
nothing to fail.

## What is here

### `yaml/` — PyYAML 6.0.2

Copied verbatim from the PyPI wheel `PyYAML==6.0.2`, with two deletions:

- `_yaml*.so` — the optional libyaml C extension. PyYAML works without it; the pure-
  Python loader is slower, which is irrelevant for files of this size. Keeping it would
  tie the repository to one platform and one Python minor version, which is the opposite
  of the point.
- `__pycache__/`

248 KB of `.py`. Licence: MIT. Copyright (c) 2017-2021 Ingy döt Net,
(c) 2006-2016 Kirill Simonov. Upstream: <https://github.com/yaml/pyyaml>

### Why not a hand-written YAML subset parser

`katana_build.load_yaml_simple`'s docstring once claimed to be a "Minimal YAML-subset
loader (avoids PyYAML dependency)". That function was never written — its body imports
`yaml` and exits if it is missing. Writing it would be the wrong trade: this project's
entire thesis is the absence of subtle bugs, and a bespoke parser for a format with
flow mappings, block mappings, nested lists, comments and quoted colons is a generator
of subtle bugs. Vendor the real one.

## How it is loaded

`vendor_path.ensure()`, at the repository root, appends this directory to `sys.path`.
Appended rather than prepended on purpose: an installed PyYAML wins, so a developer
working in a virtual environment keeps using theirs, and the vendored copy is the
fallback that makes a bare machine work.

## Updating

Replace the directory from a fresh wheel, delete `*.so` and `__pycache__`, then run all
four suites and record the new version above:

```
python3 verify.py
python3 test_determinism.py
cd kagami && python3 tests.py && python3 test_identify.py
```
