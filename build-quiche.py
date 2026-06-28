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

Source: https://github.com/cloudflare/quiche
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

QUICHE_VERSION = "0.24.6"
QUICHE_REPO = "https://github.com/cloudflare/quiche.git"


def parse_args():
    parser = argparse.ArgumentParser(description="Build quiche static library")
    parser.add_argument("platform", choices=["mac", "linux", "win"], help="Target platform")
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


def main():
    args = parse_args()

    root_dir = Path(__file__).parent.absolute()
    build_dir = Path(args.out)

    # Ensure cargo/rustup is available.
    try:
        subprocess.check_call(["cargo", "--version"], stdout=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Error: 'cargo' not found. Please install Rust.")
        sys.exit(1)

    src_dir = ensure_source(root_dir, args.version)

    archs = [a.strip() for a in args.archs.split(",")]
    profile = "release" if args.config == "Release" else "debug"

    for arch in archs:
        target = get_rust_target(args.platform, arch)
        print(f"Building quiche for {args.platform} {arch} ({target})...")

        run_command(["rustup", "target", "add", target])

        cargo_cmd = [
            "cargo", "build", "--target", target,
            "--package", "quiche", "--features", "ffi",
        ]
        if args.config == "Release":
            cargo_cmd.append("--release")
        run_command(cargo_cmd, cwd=src_dir)

        # quiche's staticlib is libquiche.a (unix) / quiche.lib (windows).
        if args.platform == "win":
            src_lib = src_dir / "target" / target / profile / "quiche.lib"
            lib_name = "quiche.lib"
        else:
            src_lib = src_dir / "target" / target / profile / "libquiche.a"
            lib_name = "libquiche.a"

        if not src_lib.exists():
            print(f"Error: expected build artifact not found: {src_lib}")
            sys.exit(1)

        # On mac we ship one zip per arch (like libuv), so nest under <arch>.
        if args.platform == "mac":
            dest_dir = build_dir / "quiche-mac" / "lib" / arch
        else:
            dest_dir = build_dir / f"quiche-{args.platform}" / "lib"
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
