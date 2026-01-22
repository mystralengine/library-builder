# Task: Add SWC Static Library Build

## Goal
Build SWC as a **static library** (e.g., `libswc.a` / `swc.lib`) in `library-builder` so the Mystral native runtime can embed TypeScript transpilation directly into the C++ binary with no extra files.

## Background
MystralNative needs fast TS type-stripping + ESM transform for dev mode. We want SWC embedded in the runtime. There is no official `libswc.a`, so we need to build SWC ourselves as a Rust `staticlib` and expose a small C ABI.

## Output Expectations
- A static library per platform:
  - macOS: `libswc.a`
  - Linux: `libswc.a`
  - Windows: `swc.lib`
- A single C header (e.g., `swc.h`) with a minimal API
- Version pinned in a reproducible way
- Artifacts stored under a consistent `dist/` layout (match existing libs)

## Proposed C ABI
Create a tiny Rust wrapper crate that exposes only what we need now:

```c
// swc.h
#ifdef __cplusplus
extern "C" {
#endif

// Returns 0 on success, non-zero on error. Output is heap-allocated and must be freed.
int swc_transpile_ts(const char* source,
                     const char* filename,
                     const char* source_map_mode, // "none" | "inline" | "file"
                     char** out_js,
                     char** out_sourcemap,
                     char** out_error);

// Free buffers allocated by SWC.
void swc_free(char* ptr);

#ifdef __cplusplus
} // extern "C"
#endif
```

Notes:
- Start with TS type-stripping + ESM output. No typecheck.
- Keep allocations owned by Rust; `swc_free` handles them.
- If sourcemaps are too much for v1, return `out_sourcemap = NULL`.

## Rust Wrapper Crate
- New directory (suggestion): `third_party/swc-static/`
- `Cargo.toml`:
  - `crate-type = ["staticlib"]`
  - Dependencies:
    - `swc_common`
    - `swc_ecma_parser`
    - `swc_ecma_codegen`
    - `swc_ecma_transforms_typescript`
    - `swc_ecma_transforms_base` (if needed)
- Expose the C ABI with `#[no_mangle] extern "C"`.
- Use `swc_ecma_parser` to parse TS/TSX, then apply `typescript::strip()` (or equivalent), then `swc_ecma_codegen` to emit JS.

## Build Steps (per platform)
1. Ensure Rust toolchain is available (stable).
2. Build staticlib:
   - `cargo build --release --target <platform-target>`
3. Copy outputs to `dist/swc/<platform>/` along with `swc.h`.

### Target Triples
- macOS arm64: `aarch64-apple-darwin`
- macOS x64: `x86_64-apple-darwin`
- Linux x64: `x86_64-unknown-linux-gnu`
- Windows x64: `x86_64-pc-windows-msvc`

(Extend later to iOS/Android once the runtime needs it.)

## Library-Builder Integration
- Add `build-swc.py` (or a Makefile target) similar to `build-skia.py` and `build-webp.py`.
- Include:
  - git clone / version pin for SWC crates (or use Cargo.lock in repo)
  - build per platform
  - copy artifacts to dist

## Version Pinning
- Pin via `Cargo.lock` or explicit `=x.y.z` versions in `Cargo.toml`.
- Record in README/notes which SWC version is used.

## Validation
- Provide a tiny C++ test (optional) that calls `swc_transpile_ts` on a sample TS file and writes output.
- Confirm emitted JS runs in the Mystral runtime.

## References
- SWC crates: https://crates.io/crates/swc_ecma_parser
- SWC typescript transform: https://crates.io/crates/swc_ecma_transforms_typescript

