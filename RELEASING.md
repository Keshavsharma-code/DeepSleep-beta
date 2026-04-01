# Releasing DeepSleep

## Fast path

1. Create the `deepsleep-ai` project on PyPI.
2. Enable Trusted Publishing for this GitHub repository:
   - owner: `Keshavsharma-code`
   - repo: `DeepSleep-beta`
   - workflow: `.github/workflows/publish.yml`
   - environment: leave blank unless you want one
3. Create a GitHub release.
4. The publish workflow will upload the wheel and sdist automatically.

## Manual path

If you want to publish from your machine instead:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade build twine
python -m build
twine check dist/*
twine upload dist/*
```

For token auth:

```bash
export TWINE_USERNAME=__token__
export TWINE_PASSWORD=pypi-...
twine upload dist/*
```

## Before releasing

```bash
pytest -q
python -m build
twine check dist/*
ds --version
ds doctor
```
