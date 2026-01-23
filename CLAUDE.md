# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This repository (mystralengine/library-builder) provides Python scripts and GitHub Actions workflows for building static libraries for Mystral Engine dependencies.

**Currently supported:**
- **Skia** - 2D graphics library with GPU support (Dawn/Graphite/Metal/Vulkan)
- **libwebp** - WebP codec for image encoding/decoding
- **SWC** - Speedy Web Compiler for TypeScript compilation

**Fork of:** [olilarkin/skia-builder](https://github.com/olilarkin/skia-builder)

## Build Scripts

| Script | Purpose | Platforms |
|--------|---------|-----------|
| `build-skia.py` | Build Skia graphics library | macOS, iOS, visionOS, Android, Windows, Linux, WASM |
| `build-webp.py` | Build libwebp codec | macOS, iOS, visionOS, Android, Windows, Linux, WASM |
| `build-swc.py` | Build SWC TypeScript compiler | macOS (arm64, x86_64), Linux, Windows |

## Build Commands

Prerequisites: ninja, python3, cmake. On Windows, LLVM must be installed at `C:\Program Files\LLVM\`. On Linux, install build dependencies: `libfontconfig1-dev libgl1-mesa-dev libglu1-mesa-dev libx11-xcb-dev libwayland-dev`.

```bash
# May need to increase file limit on macOS first
ulimit -n 2048

# Build libraries directly
python3 build-skia.py mac                          # macOS universal (arm64 + x86_64)
python3 build-skia.py ios                          # iOS (arm64 + x86_64 simulator)
python3 build-skia.py visionos                     # visionOS (arm64)
python3 build-skia.py android                      # Android arm64
python3 build-skia.py win                          # Windows x64 (static CRT)
python3 build-skia.py linux                        # Linux x64
python3 build-skia.py wasm                         # WebAssembly
python3 build-skia.py xcframework                  # Apple XCFramework (macOS + iOS)

# Options
python3 build-skia.py <platform> -config Debug     # Debug build (default: Release)
python3 build-skia.py <platform> -branch main      # Specific Skia branch (default: main)
python3 build-skia.py <platform> --shallow         # Shallow clone
python3 build-skia.py <platform> -archs x86_64,arm64  # Specific architectures

# Windows CRT options
python3 build-skia.py win -crt static              # Static CRT (/MT, /MTd) - default
python3 build-skia.py win -crt dynamic             # Dynamic CRT (/MD, /MDd)

# Android options
python3 build-skia.py android -archs arm64         # ARM64 (default)
python3 build-skia.py android -archs arm           # ARMv7
python3 build-skia.py android -archs x64           # x86_64
python3 build-skia.py android -ndk /path/to/ndk    # Custom NDK path
```

**Makefile shortcuts (from macOS):**
```bash
make skia-mac           # Build macOS libraries
make skia-ios           # Build iOS libraries
make skia-wasm          # Build WASM libraries
make skia-xcframework   # Build XCFramework
make example-mac        # Build and run example (./example/build-mac/example)
make example-wasm       # Build WASM example
make serve-wasm         # Serve WASM example on localhost:8080
make clean              # Remove build directory
```

## Architecture

**build-skia.py** - Main build script containing:
- `SkiaBuildScript` class orchestrating the entire build process
- GN argument constants (`RELEASE_GN_ARGS`, `PLATFORM_GN_ARGS`) defining Skia build configuration
- `LIBS` dict specifying which libraries to build per platform
- `PACKAGE_DIRS` defining which headers to copy to output

**Build output structure:**
```
build/
├── src/skia/          # Cloned Skia source
├── tmp/               # depot_tools, intermediate builds
├── include/           # Packaged headers
├── mac-gpu/lib/       # macOS libraries (GPU variant)
├── ios-gpu/lib/       # iOS libraries (per-arch)
├── visionos-gpu/lib/  # visionOS libraries (arm64)
├── android-gpu/lib/   # Android libraries (per-arch)
├── win-gpu/lib/       # Windows libraries (static CRT)
├── win-gpu-md/lib/    # Windows libraries (dynamic CRT)
├── linux-gpu/lib/     # Linux libraries
├── wasm-gpu/lib/      # WASM libraries
└── xcframework/       # XCFramework output
```

**Key configuration:**
- `USE_LIBGRAPHEME` constant toggles between libgrapheme and ICU for Unicode
- `MAC_MIN_VERSION` / `IOS_MIN_VERSION` / `ANDROID_MIN_API` set deployment targets
- `EXCLUDE_DEPS` lists Skia dependencies to skip during sync

## Platform-Specific Notes

### visionOS Support
visionOS builds use a workaround because **GN doesn't recognize visionOS/xros as a valid target OS**.

**Our approach:** Use `target_os = "ios"` with explicit visionOS SDK and compiler flags:
- `-target arm64-apple-xros1.0` tells clang to use the visionOS target triple
- `-isysroot <path>` explicitly points to the visionOS SDK

### Android Support
Android builds require the NDK. Set via:
- `-ndk /path/to/ndk` argument
- `ANDROID_NDK_HOME` environment variable
- `ANDROID_NDK_ROOT` environment variable

Supported architectures: `arm64`, `arm`, `x64`, `x86`

### Windows CRT Options
Windows builds support both static and dynamic CRT:
- `-crt static` (default): `/MT` for Release, `/MTd` for Debug
- `-crt dynamic`: `/MD` for Release, `/MDd` for Debug

Use static CRT with vcpkg `x64-windows-static` triplet.
Use dynamic CRT with Dawn or other dynamic CRT dependencies.

## CI

The GitHub Actions workflow (`.github/workflows/build-skia.yml`) builds all platforms in parallel and creates releases.

**Scheduled builds:** Weekly on Monday at 9:00 AM UTC (Sunday 1:00 AM PST)

**Workflow inputs:**
- `skia_branch` - Skia branch to build (default: `main`)
- `platforms` - Platforms to build, comma-separated or `all` (default: `all`)
- `skip_release` - Skip creating release, useful for testing (default: `false`)
- `test_mode` - Skip actual build, create dummy files (default: `false`)

```bash
# Build all platforms and create release
gh workflow run build-skia.yml

# Build specific platform(s) without release
gh workflow run build-skia.yml -f platforms=android -f skip_release=true
gh workflow run build-skia.yml -f platforms=mac,ios -f skip_release=true

# Build with different Skia branch
gh workflow run build-skia.yml -f skia_branch=chrome/m145

# Check CI status
gh run list
gh run view <run-id> --log-failed

# Create XCFramework from existing release (without rebuilding)
gh workflow run create-xcframework.yml -f release_tag=main-20260121
```

## Build Matrix

| Platform | Architectures | Variants | Notes |
|----------|---------------|----------|-------|
| macOS | universal, arm64, x86_64 | GPU | Dawn/Metal |
| iOS | device-arm64, simulator-arm64+x86_64 | GPU | Dawn/Metal |
| visionOS | device-arm64, simulator-arm64 | GPU | Dawn/Metal |
| Android | arm64, arm, x64 | GPU | Native Vulkan (no Dawn due to NDK C++20 issues) |
| Windows | x64 | GPU + static CRT, GPU + dynamic CRT | Dawn/D3D |
| Linux | x64 | GPU | Dawn/Vulkan |
| WASM | wasm32 | GPU | WebGL/WebGPU (Ganesh only, no Graphite) |

## Skia Libraries Built

**Core libraries (all platforms):**
- `libskia.a` - Core 2D graphics
- `libskshaper.a` - Text shaping with HarfBuzz
- `libskparagraph.a` - Paragraph layout
- `libsvg.a` - SVG rendering
- `libskunicode_core.a` + `libskunicode_icu.a` - Unicode support

**Additional libraries (most platforms, not WASM):**
- `libskottie.a` - Vector animation (Lottie)
- `libsksg.a` - Scene graph

**GPU libraries:**
- `libdawn_combined.a` - WebGPU abstraction (macOS, iOS, visionOS, Windows, Linux)
- `libEGL.a` / `libGLESv2.a` - ANGLE for WebGL/OpenGL ES translation

## Troubleshooting

### Build Failures

**WASM "unknown target 'libskottie.a'":**
- WASM disables skottie in GN args, so these targets don't exist
- The `LIBS["wasm"]` dict should not include skottie/sksg
- Fixed in commit `cdfd5a2`

**visionOS build issues:**
- GN doesn't recognize "xros" as a target OS
- We use `target_os = "ios"` with explicit `-target arm64-apple-xros1.0` flags
- See `generate_gn_args()` for the workaround

**Android Dawn C++20 errors:**
- Android NDK's libc++ lacks `std::lexicographical_compare_three_way`
- Dawn is disabled for Android; uses native Vulkan directly
- Set `skia_use_dawn = false` in Android GN args

**Windows CRT mismatches:**
- Static CRT (`/MT`) and dynamic CRT (`/MD`) builds cannot be mixed
- Choose one based on your other dependencies
- Dawn typically requires dynamic CRT

### CI/CD

**Artifacts not appearing in release:**
- Check that all matrix jobs succeeded
- Release only created when `platforms=all` and `skip_release=false`
- Artifacts from failed runs can be downloaded individually

**Cache issues:**
- Cache key includes `build-skia.py` hash and branch name
- Force cache rebuild by modifying `build-skia.py` or using different branch

## Release Artifacts

Each release includes zip files with this naming convention:
```
skia-build-{platform}-{target}-{arch}-{crt}-{variant}-{config}.zip
```

Examples:
- `skia-build-mac-universal-gpu-release.zip`
- `skia-build-ios-device-arm64-gpu-release.zip`
- `skia-build-ios-simulator-arm64-x86_64-gpu-release.zip`
- `skia-build-win-x64-static-gpu-release.zip`
- `skia-build-win-x64-dynamic-gpu-debug.zip`
- `Skia.xcframework.zip` (combined Apple platforms)

## Other Workflows

### libwebp (`build-webp.yml`)
```bash
gh workflow run build-webp.yml
```
Builds: `libwebp.a`, `libwebpdecoder.a`, `libwebpdemux.a`, `libwebpmux.a`, `libsharpyuv.a`

### SWC (`build-swc.yml`)
```bash
gh workflow run build-swc.yml
```
Builds Rust-based SWC compiler as static library for C++ integration.

### XCFramework from Release (`create-xcframework.yml`)
```bash
gh workflow run create-xcframework.yml -f release_tag=main-20260121
```
Creates XCFramework from existing release without rebuilding.
