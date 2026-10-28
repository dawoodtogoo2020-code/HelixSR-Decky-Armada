# Build dependency review

Reviewed 28 October 2026; reassess by 28 November 2026 or when the dependency changes.

The locked build tool @rollup/plugin-node-resolve 15.2.3 uses deepmerge 4.3.1. [GHSA-gcqx-w48m-w2h4](https://github.com/advisories/GHSA-gcqx-w48m-w2h4) describes prototype poisoning from attacker-controlled merge inputs. GitHub lists no patched version at the time of review. This is an acknowledged build dependency finding, not a claim that the dependency itself is fixed.

In the reviewed ES entry, deepMerge is called once: `deepFreeze(deepMerge({}, defaults))`. The source is a fixed literal containing resolver defaults, not package contents, game files, UI input or the resolver's options argument. Options use object spread separately. Our Rollup configuration calls `nodeResolve({ browser: true })` only while building. See the [pinned upstream source](https://github.com/rollup/plugins/blob/node-resolve-v15.2.3/packages/node-resolve/src/index.js).

CI still obtains the complete pnpm audit report. scripts/check_dependency_audit.py permits only this exact low-severity GHSA, dependency version and development-only path while checking the resolver's exact reviewed source hash and an expiry. Unknown findings, changed paths, runtime occurrences, changed source, an available upstream patch and an expired exception fail the check. The checker has rejection tests. This does not use a broad severity downgrade or omit production/development dependencies from the audit.

The distributable ZIP allowlist excludes node_modules, the resolver and deepmerge. Generated model/runtime files are also excluded. Remove the exception when the dependency is fixed or replaced, and reassess whenever the toolchain or input path changes.
