# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This repository (mystralengine/library-builder) provides Python scripts and GitHub Actions workflows for building static libraries for Mystral Engine dependencies. Currently supports Skia, with plans to add V8, ANGLE, and other libraries.

The Skia build script supports multiple platforms (macOS, iOS, visionOS, Android, Windows, Linux, WASM) and automates build environment setup, repository cloning, GN argument configuration, and compilation.

**Fork of:** [olilarkin/skia-builder](https://github.com/olilarkin/skia-builder)

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
| Android | arm64, arm, x64 | GPU | Dawn/Vulkan |
| Windows | x64 | GPU + static CRT, GPU + dynamic CRT | Dawn/D3D |
| Linux | x64 | GPU | Dawn/Vulkan |
| WASM | wasm32 | GPU | WebGL/WebGPU |
