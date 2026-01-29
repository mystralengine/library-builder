# Writing Patches for library-builder

This guide explains how to create proper patch files for fixing upstream dependencies like Skia, Dawn, etc.

## Why Use Git to Generate Patches

**Never manually write patch files.** Manually-written patches are error-prone:
- Incorrect line numbers
- Missing space prefix on blank context lines
- Wrong index hashes
- Corrupt patch format errors

Instead, use git to generate patches deterministically from actual file changes.

## Workflow for Creating Patches

### 1. Create a Temporary Git Repository

```bash
# Create a temp directory and initialize git
mkdir -p /tmp/patch-workspace
cd /tmp/patch-workspace
rm -rf * .git 2>/dev/null
git init
```

### 2. Download the Original Source Files

Download the source files from the upstream repository. For Dawn (from Google Source):

```bash
# Create the directory structure matching the target path
mkdir -p third_party/externals/dawn/src/dawn/native/d3d11

# Download the file (Google Source uses base64 encoding)
curl -sL "https://dawn.googlesource.com/dawn/+/refs/heads/main/src/dawn/native/d3d11/SharedFenceD3D11.cpp?format=TEXT" \
  | base64 -d > third_party/externals/dawn/src/dawn/native/d3d11/SharedFenceD3D11.cpp
```

For GitHub-hosted repos:

```bash
curl -sL "https://raw.githubusercontent.com/user/repo/main/path/to/file.cpp" \
  > path/to/file.cpp
```

### 3. Commit the Original Files

```bash
git add .
git commit -m "Original source files"
```

### 4. Make Your Changes

Edit the files to fix the issue. Use your preferred editor or sed/awk for simple changes:

```bash
# Example: Add a #include after an existing one
sed -i '' 's/#include "dawn\/native\/d3d\/PlatformFunctions.h"/#include "dawn\/native\/d3d\/PlatformFunctions.h"\n#include "dawn\/native\/d3d11\/BufferD3D11.h"/' \
  third_party/externals/dawn/src/dawn/native/d3d11/SharedFenceD3D11.cpp
```

Or simply edit the file directly with any text editor.

### 5. Generate the Patch

```bash
git diff > ~/Projects/mystral/internal_packages/library-builder/patches/my-fix.patch
```

### 6. Verify the Patch

Check that the patch looks correct:

```bash
cat patches/my-fix.patch
```

A valid patch should have:
- `diff --git a/... b/...` header
- `index xxxxxxx..yyyyyyy` line
- `--- a/...` and `+++ b/...` lines
- `@@ -N,M +N,M @@` hunk headers
- Context lines starting with a single space (including blank lines!)
- Added lines starting with `+`
- Removed lines starting with `-`

## Example: Dawn D3D11 Buffer Include Patch

This patch fixes a missing include that causes "incomplete type" errors:

```bash
# 1. Setup
mkdir -p /tmp/dawn-patch && cd /tmp/dawn-patch
git init

# 2. Create directory structure
mkdir -p third_party/externals/dawn/src/dawn/native/d3d11

# 3. Download original files
curl -sL "https://dawn.googlesource.com/dawn/+/refs/heads/main/src/dawn/native/d3d11/SharedFenceD3D11.cpp?format=TEXT" \
  | base64 -d > third_party/externals/dawn/src/dawn/native/d3d11/SharedFenceD3D11.cpp

curl -sL "https://dawn.googlesource.com/dawn/+/refs/heads/main/src/dawn/native/d3d11/TextureD3D11.cpp?format=TEXT" \
  | base64 -d > third_party/externals/dawn/src/dawn/native/d3d11/TextureD3D11.cpp

# 4. Commit originals
git add . && git commit -m "Original Dawn source"

# 5. Make changes (add BufferD3D11.h include to both files)
# ... edit files ...

# 6. Generate patch
git diff > patches/dawn-d3d11-buffer-include.patch
```

## Applying Patches in build-skia.py

Patches in the `patches/` directory are automatically applied by `build-skia.py` after syncing dependencies. The script uses `git apply` with fuzzy matching:

```python
subprocess.run(["git", "apply", "--ignore-whitespace", "-p1", patch_path], ...)
```

If a patch fails to apply, the build will show a warning but continue (patches may become unnecessary after upstream fixes).

## Testing Patches

Test patches locally before pushing:

```bash
# Test apply (dry run)
cd build/src/skia
git apply --check ../../../patches/my-fix.patch

# Apply for real
git apply --ignore-whitespace -p1 ../../../patches/my-fix.patch
```

## Patch Naming Convention

Use descriptive names that identify the component and issue:
- `dawn-d3d11-buffer-include.patch` - Dawn D3D11 missing include fix
- `skia-macos-deployment-target.patch` - Skia macOS deployment target fix
- `angle-vulkan-validation.patch` - ANGLE Vulkan validation fix

## Troubleshooting

### "corrupt patch at line N"

The patch format is invalid. Common causes:
- Blank context lines missing the leading space
- Incorrect hunk headers (`@@ -N,M +N,M @@`)
- Mixed line endings (CRLF vs LF)

**Solution:** Regenerate the patch using git diff.

### "patch does not apply"

The upstream source has changed. The patch may need to be updated or is no longer necessary.

**Solution:**
1. Check if upstream fixed the issue
2. If not, regenerate the patch against the new source

### "Hunk #N FAILED"

The context lines don't match the target file. This happens when:
- Line numbers shifted due to other changes
- The specific code being patched was modified

**Solution:** Regenerate the patch with `-p0` path stripping or update the patch.
