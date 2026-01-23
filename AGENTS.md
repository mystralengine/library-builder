# AGENTS.md

This file describes how AI coding agents can effectively work with this repository.

## Repository Context

This is a **build automation repository** for cross-platform static libraries. The primary artifacts are:
- Pre-built libraries (`.a`, `.lib` files)
- Headers
- GitHub Actions workflows for CI/CD

## Key Agent Tasks

### 1. Build Script Maintenance

When modifying `build-skia.py`, `build-webp.py`, or `build-swc.py`:
- **Understand platform differences**: Each platform has unique GN args, compiler flags, and SDK requirements
- **Test locally first**: Use `python3 build-skia.py <platform>` before pushing
- **Update LIBS dict carefully**: Platform-specific libraries (e.g., WASM disables skottie)
- **Check GPU_LIBS and ANGLE_LIBS**: Dawn availability varies by platform

### 2. CI/CD Workflow Management

**Triggering builds:**
```bash
gh workflow run build-skia.yml                              # Full build + release
gh workflow run build-skia.yml -f platforms=wasm            # Single platform
gh workflow run build-skia.yml -f skip_release=true         # No release
```

**Debugging failures:**
```bash
gh run list --workflow=build-skia.yml
gh run view <run-id> --log-failed
gh api repos/mystralengine/library-builder/actions/artifacts --jq '.artifacts[].name'
```

**Creating releases from existing artifacts:**
- The workflow only creates releases when all platforms succeed
- Individual artifacts can be downloaded from workflow runs
- Use `create-xcframework.yml` to build XCFramework from release

### 3. Platform-Specific Considerations

| Platform | Special Handling |
|----------|------------------|
| visionOS | Uses `target_os = "ios"` with `-target arm64-apple-xros1.0` flag workaround |
| Android | No Dawn (NDK C++20 issues), uses native Vulkan |
| WASM | No skottie/sksg, uses Emscripten, Ganesh only (no Graphite) |
| Windows | Dual CRT variants (static `/MT` and dynamic `/MD`) |
| iOS | Separate device and simulator builds, different SDK paths |

### 4. Adding New Platforms or Features

When adding a new platform:
1. Add entry to `LIBS` dict with platform-specific libraries
2. Add entry to `GPU_LIBS` if Dawn is supported
3. Add entry to `ANGLE_LIBS` if ANGLE is needed
4. Add `PLATFORM_GN_ARGS` configuration
5. Update `get_default_archs()` and `validate_archs()`
6. Add matrix entry in `.github/workflows/build-skia.yml`
7. Update documentation in `CLAUDE.md` and `README.md`

### 5. Investigating Build Failures

Common patterns:
- **"unknown target"**: Library not generated (check GN args vs LIBS dict)
- **Linker errors**: Missing dependencies or CRT mismatch
- **SDK errors**: Check SDK path generation in `generate_gn_args()`
- **Timeout**: Large builds may need extended timeouts

Debugging steps:
1. Check which jobs failed: `gh run view <id> --json jobs`
2. Get failed logs: `gh run view <id> --log-failed`
3. Search for specific errors: `grep -i "error\|failed" <log>`
4. Compare with successful runs to identify changes

## Agent Capabilities Needed

### Required Tools
- `gh` CLI for GitHub Actions management
- `git` for version control
- File read/write for script modifications
- Bash execution for local testing

### Knowledge Areas
- GN build system (Google's meta-build system)
- Cross-platform compilation (different compilers, SDKs, flags)
- GitHub Actions workflow syntax
- Python scripting

## Common Agent Workflows

### Fix Build Failure
1. Identify failed job from `gh run list`
2. Get logs with `gh run view <id> --log-failed`
3. Identify root cause (GN args, LIBS dict, SDK paths)
4. Make fix in Python script
5. Trigger rebuild: `gh workflow run build-skia.yml -f platforms=<platform> -f skip_release=true`
6. Verify success before full rebuild

### Create Release
1. Ensure all platforms build successfully
2. Trigger full build: `gh workflow run build-skia.yml`
3. Monitor with `gh run watch <id>` or check status periodically
4. Release created automatically with tag format `main-YYYYMMDD`

### Update Skia Version
1. Check available branches: `git ls-remote --heads https://github.com/google/skia.git`
2. Trigger build with new branch: `gh workflow run build-skia.yml -f skia_branch=chrome/m150`
3. Test for breaking changes in GN args or build process
4. Update documentation if successful

## File Quick Reference

| File | Purpose |
|------|---------|
| `build-skia.py` | Main Skia build script (~1350 lines) |
| `build-webp.py` | libwebp build script |
| `build-swc.py` | SWC compiler build script |
| `.github/workflows/build-skia.yml` | Skia CI/CD workflow |
| `.github/workflows/build-webp.yml` | libwebp CI/CD workflow |
| `.github/workflows/build-swc.yml` | SWC CI/CD workflow |
| `.github/workflows/create-xcframework.yml` | XCFramework assembly from release |
| `patches/` | Directory for patches to apply to Skia source |
| `Makefile` | Local build shortcuts |
