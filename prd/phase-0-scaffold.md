# Phase 0 — Scaffold

## Problem Statement

There is currently no place to write code. The design for the talking-head-first short-form video generator is fully captured in the glossary (`CONTEXT.md`) and the five ADRs, and the build order is laid out in the implementation plan, but the repository is an empty shell. A backend engineer who sits down to start on the contract types in Phase 1 has nowhere to put `kernel/composition.py`, no way to run a linter or a type checker, no test runner, no dependency manifest, and no Node/Remotion project to eventually shell out to. Without a consistent toolchain, every contributor and every authoring agent that touches the codebase would invent their own conventions, dependency pinning would drift, and the "monolith-first, service-shaped" structure from ADR 0003 would never get a skeleton to grow into.

The cost of skipping this phase is felt in every later phase: type checking that should catch malformed Pydantic models would not run, the per-phase `pytest` suites described in the testing approach would have no harness, and the Python ↔ Remotion ↔ IR seam that Phase 2 must de-risk would have no Node project folder to point a subprocess at. This phase exists to remove all of that friction once, up front.

## Solution

Stand up the project foundation: a `uv`-managed Python project with a `pyproject.toml` and a `src/` layout, configured for `ruff` (lint), `mypy` (type check), and `pytest` (test), plus the full package skeleton under `src/videogen/` exactly as enumerated in the implementation plan's "Repo structure" section, and a bootstrapped Node/Remotion project folder under `backends/remotion/project/`.

After this phase, a backend engineer can clone the repository, run `uv sync`, and immediately have a working environment where `uv run ruff check`, `uv run mypy`, and `uv run pytest` all execute (even if there is nothing meaningful to lint, type, or test yet). The package tree mirrors the three-service-plus-shared-kernel shape from ADR 0003, so when domain logic arrives in later phases it lands in a predictable home. The Remotion project folder exists and its Node dependencies install, so the Phase 2 render seam has a concrete target. No domain logic, no Composition types, no IR, no plugins, no agent behavior is built here — this phase delivers the toolchain and the empty rooms of the house, nothing that lives in them.

## User Stories

1. As a backend engineer, I want a `pyproject.toml` managed by `uv`, so that dependencies are declared in one modern manifest and resolved reproducibly.
2. As a backend engineer, I want a `src/` layout (the package lives under `src/videogen/`), so that imports resolve against the installed package rather than the working directory and tests exercise the real distribution shape.
3. As a backend engineer, I want `uv sync` to create a working virtual environment from a lockfile, so that every contributor and CI runner gets an identical dependency set.
4. As a platform maintainer, I want Python's version pinned in the project metadata, so that `mypy`, Pydantic v2, and the rest of the toolchain behave consistently across machines.
5. As a backend engineer, I want `ruff` configured for linting (and formatting) in `pyproject.toml`, so that style and common-error checks run uniformly with a single command.
6. As a backend engineer, I want `mypy` configured for strict-enough type checking in `pyproject.toml`, so that the Pydantic v2 Composition and IR models added in Phase 1 are statically verified rather than trusted by convention.
7. As a backend engineer, I want `pytest` configured with a discoverable `tests/` directory, so that the per-phase test suites described in the testing approach have a harness to run in from day one.
8. As a platform maintainer, I want `uv run ruff check`, `uv run mypy`, and `uv run pytest` to all succeed on a fresh checkout, so that "green on an empty repo" is the known-good baseline before any domain code lands.
9. As a kernel developer, I want a `kernel/` package created (with placeholders for `composition.py`, `ir.py`, `registry.py`, `builder.py`, `validator.py`, `resolver.py`, `compile_ir.py`), so that the shared kernel that all three services import (per ADR 0003) has its home staked out before Phase 1 fills it.
10. As a kernel developer, I want the `kernel/` package to be importable on its own with zero render or service dependencies, so that the "render facet stays pure data and can sit in the shared kernel" requirement from ADR 0002 is structurally enforced from the start.
11. As a plugin author, I want a `plugins/` package with `layouts/`, `overlays/`, and `captions/` subpackages laid out, so that the registry-extensible structure from ADR 0001 and 0002 (a plugin folder per type holding `contract.py` + `ir.py`) has its scaffolding ready.
12. As a backend engineer, I want a `backends/` package with `base.py` reserved for the `RenderBackend` protocol and a `remotion/` subpackage, so that the swappable-backend boundary from ADR 0002 is expressed in the directory layout even before any backend is implemented.
13. As a backend engineer, I want a `services/` package with placeholders for `media.py`, `render.py`, and `authoring.py`, so that the three services from ADR 0003 each have a single-purpose module reserved.
14. As a platform maintainer, I want a `stores/` package with placeholders for `composition_store.py` and `blobs.py`, so that the persistence seam (snapshot undo, append-only journal, single render-output writer with an S3-later seam) has a home consistent with the plan.
15. As an authoring-agent integrator, I want an `agent/` package with placeholders for `tools.py`, `loop.py`, `review.py`, and `prompts.py`, so that the tool-driven authoring loop and the review sub-agent from ADR 0004 have reserved modules.
16. As a creator/host using the eventual CLI, I want an `app/` package with a placeholder `cli.py`, so that the end-to-end entry point named in the plan has a defined location.
17. As a kernel developer, I want every Python subpackage to carry an `__init__.py` (or be a recognized package), so that the tree is importable and `mypy` and `pytest` can traverse it without path hacks.
18. As a platform maintainer, I want a Node/Remotion project folder bootstrapped under `backends/remotion/project/` with its own `package.json`, so that Phase 2 can shell out to `npx remotion render` / `still` against a real project (per ADR 0002).
19. As a backend engineer, I want the Remotion project's Node dependencies to install cleanly via `npm i`, so that the verification step in the plan ("install Node deps in `backends/remotion/project`") passes on a fresh checkout.
20. As a platform maintainer, I want the Python project and the Node project to coexist without their tooling colliding (lint/type config scoped to Python; Node tooling scoped to its folder), so that the polyglot repo stays maintainable.
21. As a backend engineer, I want a `.gitignore` (or equivalent) that excludes virtual environments, `node_modules`, caches, and build artifacts, so that the repository stays clean and the lockfiles remain the source of truth.
22. As a platform maintainer, I want the package metadata to declare an entry point or console script name for the eventual `videogen` CLI, so that `uv run videogen ...` (per the plan's verification) is reserved even though the command is implemented later.
23. As a backend engineer, I want a minimal smoke test that imports the top-level package, so that `pytest` has at least one passing test and the test harness is proven to work end to end.
24. As a platform maintainer, I want the toolchain choices (`uv`, Pydantic v2, `ruff`, `mypy`, `pytest`) to match the plan's "Tech choices" table exactly, so that there is no drift between the documented decisions and the actual configuration.
25. As a backend engineer, I want Pydantic v2 declared as a dependency now (even though no models exist yet), so that Phase 1 can begin writing Composition and IR types without first touching packaging.
26. As a platform maintainer, I want clear, documented commands for environment setup (`uv sync`, `npm i` in the Remotion folder), so that the onboarding path matches the plan's verification steps.
27. As a kernel developer, I want the directory layout to make it obvious where each future module goes, so that an authoring agent or a human contributor can navigate the codebase by convention rather than by searching.

## Implementation Decisions

- **Packaging and layout.** The project is packaged with `uv` and a single `pyproject.toml`, using the `src/` layout with the importable package rooted at `src/videogen/`. This matches the plan's "Tech choices" and "Repo structure" verbatim. A lockfile is committed so `uv sync` is reproducible.
- **Python toolchain configuration.** `ruff`, `mypy`, and `pytest` are all configured inside `pyproject.toml` (their respective config tables) rather than in scattered config files, keeping the single-manifest discipline. `pytest` is pointed at a top-level `tests/` directory. `mypy` is set strict enough to meaningfully check the Pydantic v2 models that arrive in Phase 1. No domain-specific lint rules are needed yet; the goal is a clean, documented baseline.
- **Dependencies declared now.** Pydantic v2 is declared as a runtime dependency because it is the foundation of the Composition and IR types (ADR 0001, 0002, 0003) built in Phase 1. Dev dependencies cover `ruff`, `mypy`, and `pytest`. Heavier runtime dependencies (`faster-whisper`, the Anthropic SDK, `ffprobe` is an external binary not a package) are deferred to the phases that introduce them, to keep the initial environment lean — though the manifest is structured so adding them later is a one-line change.
- **Package skeleton mirrors the service shape (ADR 0003).** The created tree is exactly the plan's "Repo structure": a `kernel/` shared library, a `plugins/` tree (`layouts/`, `overlays/`, `captions/`), a `backends/` tree (`base.py` + `remotion/`), a `services/` tree (`media.py`, `render.py`, `authoring.py`), a `stores/` tree (`composition_store.py`, `blobs.py`), an `agent/` tree (`tools.py`, `loop.py`, `review.py`, `prompts.py`), and an `app/` tree (`cli.py`). Each module is created as an importable placeholder with no domain logic. The directory boundaries themselves encode the architectural decisions: AuthoringService / MediaService / RenderService are separate modules, and the kernel is a standalone importable package.
- **Kernel import purity (ADR 0002, 0004).** The `kernel/` package is structured so it can be imported with zero dependencies on `backends/` or `services/`. This is the structural precondition for "the Builder, Validator, and Resolver live in the shared kernel so AuthoringService stays free of render dependencies" (ADR 0004) and for plugins' render facets being pure data (ADR 0002). Nothing enforces this with a tool yet — it is established by what the placeholder modules do and do not import.
- **Plugin folder convention (ADR 0001, 0002).** The `plugins/overlays/` and `plugins/layouts/` subtrees are laid out so each future overlay type or layout occupies its own folder holding a `contract.py` and an `ir.py` (the pure `to_ir` facet). `plugins/captions/styles.py` is reserved for the caption-style presets (`pill`, `word_bold`, `kinetic`). No plugin is implemented in this phase; only the folders exist.
- **Backend boundary (ADR 0002).** `backends/base.py` is reserved for the `RenderBackend` protocol (the eventual `render_video` / `render_still` interface), and `backends/remotion/` holds the Python subprocess wrapper plus the `project/` Node app. The directory split makes explicit that the only Remotion-specific code lives under `backends/remotion/`.
- **Node/Remotion project bootstrap.** A Node project is initialized under `backends/remotion/project/` with its own `package.json` and Remotion as a dependency, installable via `npm i`. This phase only bootstraps the folder so the subprocess target exists; the IR-to-components implementation (the three layer-kind components and the keyframe sampler) is Phase 2 work. The Node tooling is scoped entirely within this folder so it does not interfere with the Python `ruff`/`mypy`/`pytest` configuration.
- **CLI entry point reserved.** The package metadata reserves a `videogen` console-script entry point pointing at `app/cli.py`, so the plan's `uv run videogen make ...` command name is claimed even though the command body is implemented in Phase 9.
- **Repository hygiene.** A `.gitignore` excludes the virtual environment, `node_modules`, tool caches, and render artifacts, keeping lockfiles as the dependency source of truth.

## Testing Decisions

- A good test in this phase verifies externally observable behavior of the scaffold, not its internal wiring. The externally observable facts are: the package imports, the three toolchain commands run and exit successfully, and the Node project installs.
- The single meaningful unit test is a package-import smoke test that imports `videogen` (and ideally the empty `kernel` package) and asserts it loads. This proves `pytest` discovers tests under `tests/`, that the `src/` layout resolves, and that the package is installed into the environment — all external behaviors of the scaffold.
- The toolchain itself is validated by running it: `uv run ruff check` reports clean, `uv run mypy` reports no errors on the placeholder tree, and `uv run pytest` collects and passes the smoke test. These command-level checks are the phase's acceptance criteria and double as the green baseline that every later phase builds on (the plan's verification step "`uv run pytest` — all phase tests green" starts here).
- The Node project is validated by `npm i` succeeding in `backends/remotion/project/`, matching the plan's verification step.
- There is no domain logic to test in this phase, so there are deliberately no Composition round-trip tests, no IR snapshot tests, and no validator tests — those begin in Phase 1 and beyond. The prior art these later tests will follow (round-trip JSON tests, snapshot tests for IR compilation, contract tests for registry completeness, per-phase render integration tests) is described in the plan's "Testing approach"; this phase only ensures the harness that runs them exists and is green.

## Out of Scope

- Any domain logic: no Composition, Asset, Audio, Scene, Reference, Transition, Overlay, or Caption types (those are Phase 1); no IR, Layer, Value/Keyframe track, or easing (also Phase 1).
- The `RenderBackend` protocol body, the Remotion subprocess wrapper, the IR-to-components Node implementation, and the keyframe sampler (Phase 2).
- MediaService ingest/probe/transcribe/resolve behavior (Phases 2–3).
- Caption styles, the Builder, the Validator, the Resolver, the Registry, and `compile_ir` logic (Phases 3–5).
- Layout and overlay plugins, transitions, and effects (Phases 5–6).
- The CompositionStore, blobs writer, and async RenderService (Phase 7).
- The authoring agent, Builder-ops-as-tools, in-loop vision, and the review sub-agent (Phases 8–8b).
- The end-to-end CLI behavior (Phase 9).
- All v1 out-of-scope items remain out of scope: S3 storage, script→TTS / no-footage paths, distributed queue/RPC, alpha masks, structured brief schema, human editor UI, and MediaService enrichments.

## Further Notes

- This phase is intentionally thin on product value and heavy on enabling everything after it. Its success is measured by the absence of friction in Phase 1, not by any user-visible capability.
- The verification steps in the implementation plan (`uv sync`; `npm i` in the Remotion project; `ffmpeg`/`ffprobe` on PATH; `ANTHROPIC_API_KEY` set) should be reflected in setup documentation, but only the first two are exercised by this phase. The `ffmpeg`/`ffprobe` and API-key requirements are noted for the contributor's environment but are not consumed until Phases 2 and 8.
- The directory layout is reproduced exactly from the plan so that no later phase has to relocate a module. If a structural decision needs to change, it should be reflected back into the plan's "Repo structure" and the relevant ADR rather than diverging silently.
- Keeping the Node and Python toolchains cleanly separated within the repo (Python config in `pyproject.toml`, Node config inside `backends/remotion/project/`) is what lets the polyglot decision from ADR 0002 (Remotion is JS, shelled out via subprocess) stay maintainable as the project grows.
