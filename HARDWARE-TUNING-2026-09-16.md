# Gated Intel/NVIDIA hardware tuning

This complete repository includes the rebuilt served payload, manifest and pinned preseed. Publish the whole repository atomically using the existing workflow; do not deploy only individual modified runtime files.

The four btrfs p15s/p15s-duo/flex/flex-duo profiles enable both vendor installation flags. The other nine profiles contain the same parameters but disable both flags. Intel requires actual Intel CPU detection; NVIDIA also requires a selected NVIDIA addon class and an actual NVIDIA display GPU. A failed/disabled gate installs no corresponding tuning assets. The source payload still contains all choices for future hosts.

Automatic tuning and boot autostart remain off initially. Right-click the existing battery/plug icon for the new menu; left-click energy profiles are preserved. Start with Generate Hardware Tuning Report, inspect the driver-supported values and then explicitly select automatic or a single profile. Positive offsets, power increases and exclusive nonqueryable clock locks require separate acknowledgements. No guessed RAPL board limits, raw MSR writes, voltage overrides, thermal-protection disabling or unlocked-multiplier claims are introduced.

See `docs/hardware-tuning/README.md` for all 20 Intel and nine NVIDIA setting families, the four-profile defaults, source/runtime configuration, exact menu actions, unit mappings, lifecycle and recovery behavior, security boundaries and limitations. See `validation/hardware-tuning/README.md` for actual test results and `docs/hardware-tuning/ACCEPTANCE.md` for remaining on-host checks. The full repository test suite retains eight independently reproduced pre-existing/environment failures; it is not represented as all-green.

The historical workload-policy hash fixture is unchanged. Its test guard permits only the exact single new installer call, with a count check, alongside the two existing allowed additions. Existing CPU/cpuset/I/O delegation, workload weights, left-click menu commands and app isolation policy were not retuned by this feature.
