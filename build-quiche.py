#!/usr/bin/env python3
"""
Build quiche static library for multiple platforms.

quiche is Cloudflare's QUIC + HTTP/3 implementation (Rust, exposes a C FFI).
Mystral Engine uses it as the native backend for the WebTransport JS API.

We build it as a static library (libquiche.a / quiche.lib) with the `ffi`
feature, after applying a small patch that exposes
`quiche_h3_config_set_additional_settings` to the C FFI (needed to advertise
the WebTransport HTTP/3 SETTINGS that upstream quiche does not handle natively).

quiche bundles BoringSSL (a git submodule), so building requires:
  - a Rust toolchain (cargo/rustup)
  - cmake
  - Go (for BoringSSL)
  - NASM (Windows only)
  - the Android NDK + cargo-ndk (Android only)
  - Xcode + iOS SDK (iOS only)

Supported platforms: mac, linux, win (desktop), ios, android (mobile).

Source: https://github.com/cloudflare/quiche
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

QUICHE_VERSION = "0.24.6"
QUICHE_REPO = "https://github.com/cloudflare/quiche.git"

# Default deployment / API targets for mobile.
IOS_MIN_VERSION = "13.0"
ANDROID_API_LEVEL = "24"

# arch token -> Android ABI (cargo-ndk uses ABI names)
ANDROID_ABIS = {
    "arm64": "arm64-v8a",
    "armv7": "armeabi-v7a",
    "x64": "x86_64",
    "x86_64": "x86_64",
}


def parse_args():
    parser = argparse.ArgumentParser(description="Build quiche static library")
    parser.add_argument(
        "platform",
        choices=["mac", "linux", "win", "ios", "android"],
        help="Target platform",
    )
    parser.add_argument("-archs", help="Target architectures (comma separated)", default="x64")
    parser.add_argument("-config", choices=["Release", "Debug"], default="Release")
    parser.add_argument("-out", help="Output directory", default="build")
    parser.add_argument("-version", help="quiche version (git tag)", default=QUICHE_VERSION)
    return parser.parse_args()


def get_rust_target(platform, arch):
    if platform == "mac":
        if arch == "arm64":
            return "aarch64-apple-darwin"
        elif arch in ("x64", "x86_64"):
            return "x86_64-apple-darwin"
    elif platform == "linux":
        if arch in ("x64", "x86_64"):
            return "x86_64-unknown-linux-gnu"
    elif platform == "win":
        if arch in ("x64", "x86_64"):
            return "x86_64-pc-windows-msvc"
    elif platform == "ios":
        if arch == "arm64":            # physical device
            return "aarch64-apple-ios"
        elif arch == "sim-arm64":      # simulator on Apple Silicon
            return "aarch64-apple-ios-sim"
        elif arch in ("sim-x64", "sim-x86_64"):  # simulator on Intel
            return "x86_64-apple-ios"
    elif platform == "android":
        if arch == "arm64":
            return "aarch64-linux-android"
        elif arch in ("armv7", "arm"):
            return "armv7-linux-androideabi"
        elif arch in ("x64", "x86_64"):
            return "x86_64-linux-android"

    print(f"Unsupported platform/arch combination: {platform}/{arch}")
    sys.exit(1)


def run_command(cmd, cwd=None, env=None):
    print(f"Running: {' '.join(cmd)}")
    try:
        subprocess.check_call(cmd, cwd=cwd, env=env)
    except subprocess.CalledProcessError as e:
        print(f"Command failed with exit code {e.returncode}")
        sys.exit(1)


def ensure_source(root_dir, version):
    """Clone quiche (with the BoringSSL submodule) and apply the FFI patch."""
    src_dir = root_dir / "third_party" / f"quiche-{version}"

    if not (src_dir / ".git").exists():
        if src_dir.exists():
            shutil.rmtree(src_dir)
        src_dir.parent.mkdir(parents=True, exist_ok=True)
        print(f"Cloning quiche {version} (with BoringSSL submodule)...")
        run_command([
            "git", "clone", "--recursive", "--depth", "1",
            "--branch", version, QUICHE_REPO, str(src_dir),
        ])
    else:
        print(f"quiche source already present at {src_dir}")

    # Apply the WebTransport FFI patch (idempotent: skip if already applied).
    patch_path = root_dir / "patches" / "quiche-webtransport-ffi.patch"
    if patch_path.exists():
        already_applied = subprocess.run(
            ["git", "-C", str(src_dir), "apply", "--reverse", "--check", str(patch_path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ).returncode == 0
        if already_applied:
            print("quiche WebTransport FFI patch already applied")
        else:
            print("Applying quiche WebTransport FFI patch...")
            run_command(["git", "-C", str(src_dir), "apply", str(patch_path)])
    else:
        print(f"WARNING: patch not found at {patch_path} (building unpatched quiche)")

    return src_dir


def build_target(platform, arch, target, src_dir, release):
    """Invoke the right cargo build for the platform; returns the built lib path."""
    run_command(["rustup", "target", "add", target])

    profile = "release" if release else "debug"
    env = os.environ.copy()

    if platform == "ios":
        # Point cmake/clang at the correct SDK so BoringSSL (incl. its asm) is
        # built for the right platform. cmake-rs does not reliably distinguish the
        # arm64 *simulator* (aarch64-apple-ios-sim) from the arm64 device, so we
        # set SDKROOT explicitly: simulator SDK for the *-sim and x86_64 targets,
        # device SDK otherwise.
        env["IPHONEOS_DEPLOYMENT_TARGET"] = IOS_MIN_VERSION
        is_sim = target.endswith("-sim") or target.startswith("x86_64-apple-ios")
        sdk = "iphonesimulator" if is_sim else "iphoneos"
        try:
            sdk_path = subprocess.check_output(
                ["xcrun", "--sdk", sdk, "--show-sdk-path"]
            ).decode().strip()
            if sdk_path:
                env["SDKROOT"] = sdk_path
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
        cargo_cmd = ["cargo", "build", "--target", target,
                     "--package", "quiche", "--features", "ffi"]
        if release:
            cargo_cmd.append("--release")
        run_command(cargo_cmd, cwd=src_dir, env=env)

    elif platform == "android":
        # cargo-ndk wires up the NDK toolchain (linker + cc/cmake env) so quiche's
        # build.rs can cross-compile BoringSSL with the NDK. The API level is set
        # via CARGO_NDK_PLATFORM (cargo-ndk's `-p` is cargo's --package, not the
        # platform/API level).
        abi = ANDROID_ABIS.get(arch)
        if not abi:
            print(f"Unsupported Android arch: {arch}")
            sys.exit(1)
        ndk = env.get("ANDROID_NDK_HOME") or env.get("ANDROID_NDK_ROOT") \
            or env.get("ANDROID_NDK_LATEST_HOME")
        if ndk:
            env["ANDROID_NDK_HOME"] = ndk
            env["ANDROID_NDK_ROOT"] = ndk
        env["CARGO_NDK_PLATFORM"] = ANDROID_API_LEVEL
        cargo_cmd = ["cargo", "ndk", "-t", abi,
                     "build", "--package", "quiche", "--features", "ffi"]
        if release:
            cargo_cmd.append("--release")
        run_command(cargo_cmd, cwd=src_dir, env=env)

    else:  # desktop: mac / linux / win
        if platform == "win":
            # mystralnative links Windows with the STATIC MSVC runtime (/MT), like
            # Skia/V8/Dawn. quiche + its bundled BoringSSL must match, otherwise
            # linking fails with LNK2038 (MD_DynamicRelease vs MT_StaticRelease).
            # The crt-static target-feature makes Rust use /MT and cmake-rs set
            # CMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded for the BoringSSL build.
            existing = env.get("RUSTFLAGS", "")
            env["RUSTFLAGS"] = (existing + " -C target-feature=+crt-static").strip()
        cargo_cmd = ["cargo", "build", "--target", target,
                     "--package", "quiche", "--features", "ffi"]
        if release:
            cargo_cmd.append("--release")
        run_command(cargo_cmd, cwd=src_dir, env=env)

    lib_name = "quiche.lib" if platform == "win" else "libquiche.a"
    lib_path = src_dir / "target" / target / profile / lib_name
    if not lib_path.exists():
        print(f"Error: expected build artifact not found: {lib_path}")
        sys.exit(1)
    return lib_path, lib_name


def dest_lib_dir(build_dir, platform, arch, multi):
    """Where to place the built lib for packaging.

    Desktop mac and all mobile builds nest under <arch> so a single -out dir can
    hold several arches; linux/win use a flat lib/ dir.
    """
    if platform in ("ios", "android") or (platform == "mac"):
        return build_dir / f"quiche-{platform}" / "lib" / arch
    return build_dir / f"quiche-{platform}" / "lib"


def main():
    args = parse_args()

    root_dir = Path(__file__).parent.absolute()
    build_dir = Path(args.out)
    release = args.config == "Release"

    # Ensure cargo/rustup is available.
    try:
        subprocess.check_call(["cargo", "--version"], stdout=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Error: 'cargo' not found. Please install Rust.")
        sys.exit(1)

    # Android needs cargo-ndk.
    if args.platform == "android":
        try:
            subprocess.check_call(["cargo", "ndk", "--version"], stdout=subprocess.DEVNULL)
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("Error: 'cargo-ndk' not found. Install with: cargo install cargo-ndk")
            sys.exit(1)

    src_dir = ensure_source(root_dir, args.version)

    archs = [a.strip() for a in args.archs.split(",")]

    for arch in archs:
        target = get_rust_target(args.platform, arch)
        print(f"Building quiche for {args.platform} {arch} ({target})...")

        src_lib, lib_name = build_target(args.platform, arch, target, src_dir, release)

        dest_dir = dest_lib_dir(build_dir, args.platform, arch, len(archs) > 1)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_lib = dest_dir / lib_name
        print(f"Copying {src_lib} -> {dest_lib}")
        shutil.copy2(src_lib, dest_lib)

    # Copy the (patched) C header.
    header_src = src_dir / "quiche" / "include" / "quiche.h"
    header_dest = build_dir / "include" / "quiche.h"
    header_dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"Copying {header_src} -> {header_dest}")
    shutil.copy2(header_src, header_dest)

    print("Build complete.")


if __name__ == "__main__":
    main()
