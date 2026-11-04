# Day 1: Portfolio engine

![lint](https://github.com/AcuSilas/30-days-geoai/actions/workflows/lint.yml/badge.svg)

**Track:** Software · **Level:** Easy · **Time:** ~2 hours

The workshop the other 29 days run in: one repo where every project is reproducible
(exact environments recorded in lockfiles) and automatically checked (linting on every
commit, and again on a clean machine on every push).

## What I built

- A GitHub profile README introducing my work and linking to this repo
- A monorepo with Python managed by **uv** and R managed by **renv**
- **pre-commit** hooks: whitespace, end-of-file, YAML and large-file checks, ruff (Python),
  styler and lintr (R)
- A **GitHub Actions** workflow that runs the same hooks on a fresh Ubuntu machine for
  Python and R, with a status badge

## Key ideas

**Recipe vs receipt.** A manifest says what you need; a lockfile records exactly what was
installed. You edit the manifest; the tool writes the lockfile. Both go into Git.

| | Manifest (I edit) | Lockfile (tool writes) | Rebuild with |
| --- | --- | --- | --- |
| Python | `pyproject.toml` | `uv.lock` | `uv sync` |
| R | `DESCRIPTION` | `renv.lock` | `renv::restore()` |

**Three layers of checks.** The same rules run in three places, each catching what the
last one missed:

1. Editor (Positron): format on save, inline warnings
2. pre-commit: blocks a commit that fails a check
3. CI: reruns everything on a clean machine after push

**One source of truth.** CI runs `pre-commit`, not its own copy of the rules, so local and
CI can't disagree.

**Data never goes in Git.** Each day ships a download script instead. Rasters are large,
Git keeps every version forever, and some licences forbid redistribution.

## Repo layout

```
30-days-geoai/
├── .github/workflows/lint.yml   # CI
├── .pre-commit-config.yaml      # the checks
├── .lintr                       # R lint rules (skips renv/)
├── .gitignore                   # data, envs, rasters, secrets
├── pyproject.toml  uv.lock  .python-version
├── renv.lock  .Rprofile  renv/activate.R  renv/settings.json
├── data/                        # ignored; filled by download scripts
└── day-NN/README.md             # one folder per day
```

## Reproduce it

```bash
git clone https://github.com/AcuSilas/30-days-geoai.git
cd 30-days-geoai
uv sync                          # Python env from uv.lock
Rscript -e "renv::restore()"     # R library from renv.lock
uv run pre-commit install        # turn on the commit gate
uv run pre-commit run --all-files
```

## Cheatsheet

```bash
# Git setup (once)
git config --global user.email "<github email>"   # must match GitHub
git config --global core.longpaths true
git config --global init.defaultBranch main

# Python with uv
uv init --name <name> --python 3.12   # new project
uv add <pkg>                          # runtime dependency
uv add --dev <pkg>                    # dev-only tool
uv remove <pkg>
uv sync                               # rebuild env from uv.lock
uv run <cmd>                          # run inside the env
uv lock --upgrade                     # refresh versions

# pre-commit
uv run pre-commit install             # enable the gate (once per clone)
uv run pre-commit run --all-files     # check everything
uv run pre-commit autoupdate          # bump hook versions
SKIP=lintr git commit -m "..."        # skip one hook (rarely)

# Everyday loop
git status                            # what changed?
git add -A
git commit -m "feat: ..."             # hooks run here
git push                              # CI runs here
```

```r
# R with renv
renv::init(bare = TRUE)   # new project library
renv::install("pkg")      # install into it
renv::snapshot()          # write renv.lock
renv::status()            # lockfile vs library drift
renv::restore()           # rebuild from renv.lock
```

**Commit prefixes (Conventional Commits):** `feat:` new capability · `fix:` bug fix ·
`docs:` documentation · `style:` formatting only · `refactor:` restructure, no behaviour
change · `test:` tests · `chore:` tooling and setup

## What I learned

_My answers to the check questions, in my own words._

1. What happens when someone clones the repo and runs `uv sync`?
2. `pyproject.toml` vs `uv.lock`, and why committing only the first is risky
3. Two reasons CI is worth having when pre-commit already runs locally
4. Why CI runs `pre-commit` instead of calling `ruff` directly
5. Where a 2 GB raster lives, and what goes into Git instead
6. A hook reformatted a file: has anything gone wrong? What next?
7. How renv and a lockfile change onboarding for an existing R pipeline

## Further reading

- Wilson et al. (2017), [Good enough practices in scientific computing](https://doi.org/10.1371/journal.pcbi.1005510)
- [Pro Git](https://git-scm.com/book/en/v2), chapters 2–3
- [uv docs](https://docs.astral.sh/uv/) · [renv docs](https://rstudio.github.io/renv/) · [pre-commit](https://pre-commit.com/)
- [The Turing Way](https://book.the-turing-way.org/)
- [Conventional Commits](https://www.conventionalcommits.org/)
