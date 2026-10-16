# Llama and persistent Whisper memory handoff

The managed `llama` entrypoint (`/data/llama/lib/llama`), its `cli` and `server`
modes, and the AI & Copilots desktop actions share one coordinator. The
on-demand `llama-server.service` reaches the same entrypoint. Calling a release
binary directly under `/data/llama/bin` bypasses the managed entrypoint.

## Admission

Before executing a model, the coordinator reads Linux `MemAvailable` and, for
GPU offload, NVIDIA `memory.free`. Memory is checked per GPU; it is never summed
across GPUs. CPU mode does not require NVIDIA tools. Explicit `--device none`
and disabled CUDA visibility select the CPU estimate.

The estimate uses the actual selected GGUF, block count, embedding and attention
dimensions, context size, GPU layer count and KV offload setting. The managed
environment defaults and CLI model/context/layer overrides are taken into
account. RAM reserves a full weight copy, the f16 KV cache and 1 GiB of headroom.
VRAM reserves the offloaded weight fraction, any offloaded KV cache and 256 MiB
for compute buffers. These are conservative admission estimates for the managed
settings, not an exact allocator simulation. Different cache formats, extra
adapters/multimodal models, unusual tensor placement and concurrent allocations
by other applications can change actual requirements. All NVIDIA GPUs are
checked conservatively, including GPUs outside a selected device list.

For the P15s profile's Qwen2.5 Coder 7B Q4_K_M, eight GPU layers and RAM KV cache,
the estimate exceeds the example's roughly 859 MiB free VRAM. An active Whisper
server is therefore suspended before Llama loads. Profile settings and model
selection are preserved.

If memory is constrained, an active or starting **user**
`whisper-server.service` is stopped synchronously. Its inactive/failed state
and cleared main PID are checked. With CUDA, NVIDIA must report that the old
Whisper PID has disappeared for two consecutive samples. Then available memory
is checked again. If it remains insufficient, or telemetry/teardown cannot be
verified, Llama is not executed. No system service or privileged command is used.

Simple help/version requests do not evict Whisper. A service that was already
inactive is not claimed for restoration.

## Lifetime and restoration

Each coordinated Llama process inherits a shared `flock` descriptor across
`exec`. Its terminal, PID, job control, arguments, signals and exit status stay
native. The lease disappears when that process and any children inheriting it
close their descriptors, including after SIGKILL. Kernel PID descriptors also
check that the recorded Llama processes have exited, so a binary closing its
inherited descriptor early cannot cause early restoration. A reused PID is
treated conservatively as still alive and can postpone restoration.

`llama-whisper-guard.service` is started on demand before any Whisper stop. It
continues independently of Llama, polls once per second, and is restarted by
the user manager if it fails. It can restore Whisper only after the last lease
has gone and NVIDIA no longer lists the recorded process PIDs. The admission
lock serializes launch, stop and restoration. Recovery intent is written
atomically before stopping Whisper, so a failed launch or a killed caller can
still be recovered. Failed recovery is retried without discarding that intent.

An additional Whisper `ExecCondition` defers competing start requests while a
suspension is owned by active Llama processes. Whisper is restarted only while
`labwc-session.target` is active; the guard belongs to that target and stops on
logout. Whisper's existing persistent-memory and session checks still apply.

Coordination state is private, per UID, below
`/run/user/UID/llama-whisper`. Runtime directories, file ownership, file modes,
symlinks, link counts, state size and PID records are checked. External commands
use fixed argument arrays, a minimal environment and bounded timeouts/output.
Logs contain lifecycle events and failures, without prompts or model contents.

## Installation and verification

The desktop installer stages the helper, its Python module, the global user
unit and the Whisper condition. The security installer stages the shared
AppArmor abstraction; the existing Llama domains inherit its grants and the
guard has a separate profile. The installed desktop verifier checks the new
assets and their modes. No Xwayland policy, model/profile tuning, release pin,
or source compilation is changed.

`d-i/forky/tests/test_llama_whisper_coordination.py` is guarded by the repository
isolation check before imports. Manager operations, procfs memory and NVIDIA
telemetry are mocked. The lease fixture uses only the disposable image's Python
and private temporary files to check inheritance across exec and SIGKILL.

Run that suite only in the prepared disposable VM/image described in
`docs/test-isolation.md`, using its `test-init.py test --pattern
test_llama_whisper_coordination.py` stage. It must not run on the development
host. Live Forky/systemd 262, AppArmor enforcement and the pinned CUDA binaries
still require acceptance in that disposable environment; source parsing and
payload generation do not establish live behavior.
