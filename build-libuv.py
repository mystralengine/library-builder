#!/usr/bin/env python3
"""
Build libuv static library for multiple platforms.

libuv is a multi-platform support library with a focus on asynchronous I/O.
Used by Node.js and other projects for event loop and async operations.

Source: https://github.com/libuv/libuv
"""

import argparse
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

LIBUV_VERSION = "1.51.0"
LIBUV_URL = f"https://github.com/libuv/libuv/archive/refs/tags/v{LIBUV_VERSION}.zip"


def parse_args():
    parser = argparse.ArgumentParser(description="Build libuv static library")
    parser.add_argument("platform", choices=["mac", "linux", "win"], help="Target platform")
    parser.add_argument("-archs", help="Target architectures (comma separated)", default="x64")
    parser.add_argument("-config", choices=["Release", "Debug"], default="Release")
    parser.add_argument("-out", help="Output directory", default="build")
    parser.add_argument("-version", help="libuv version", default=LIBUV_VERSION)
    return parser.parse_args()


def run_command(cmd, cwd=None, env=None, shell=False):
    print(f"Running: {cmd if shell else ' '.join(cmd)}")
    try:
        subprocess.check_call(cmd, cwd=cwd, env=env, shell=shell)
    except subprocess.CalledProcessError as e:
        print(f"Command failed with exit code {e.returncode}")
        sys.exit(1)


def download_libuv(version, dest_dir):
    """Download and extract libuv source."""
    url = f"https://github.com/libuv/libuv/archive/refs/tags/v{version}.zip"
    zip_path = dest_dir / f"libuv-{version}.zip"
    extract_dir = dest_dir / f"libuv-{version}"

    if extract_dir.exists():
        print(f"libuv source already exists at {extract_dir}")
        return extract_dir

    dest_dir.mkdir(parents=True, exist_ok=True)

    print(f"Downloading libuv v{version}...")
    urllib.request.urlretrieve(url, zip_path)

    print(f"Extracting to {dest_dir}...")
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(dest_dir)

    zip_path.unlink()  # Remove zip after extraction
    return extract_dir


def get_cmake_arch_flags(platform, arch):
    """Get CMake flags for target architecture."""
    flags = []

    if platform == "mac":
        if arch == "arm64":
            flags.extend(["-DCMAKE_OSX_ARCHITECTURES=arm64"])
        elif arch in ("x64", "x86_64"):
            flags.extend(["-DCMAKE_OSX_ARCHITECTURES=x86_64"])
        # Set minimum macOS version
        flags.extend(["-DCMAKE_OSX_DEPLOYMENT_TARGET=10.15"])

    elif platform == "win":
        # Visual Studio generator handles arch via -A flag
        if arch in ("x64", "x86_64"):
            flags.extend(["-A", "x64"])
        elif arch == "x86":
            flags.extend(["-A", "Win32"])

    # Linux x64 is the default, no special flags needed

    return flags


def build_libuv(source_dir, build_dir, platform, arch, config):
    """Build libuv using CMake."""
    cmake_build_dir = build_dir / f"cmake-build-{platform}-{arch}"
    cmake_build_dir.mkdir(parents=True, exist_ok=True)

    # Base CMake arguments
    cmake_args = [
        "cmake",
        str(source_dir),
        f"-DCMAKE_BUILD_TYPE={config}",
        "-DLIBUV_BUILD_TESTS=OFF",
        "-DLIBUV_BUILD_BENCH=OFF",
        "-DBUILD_TESTING=OFF",
    ]

    # Platform-specific flags
    if platform == "win":
        # Use static CRT (/MT) for consistency with other libraries
        cmake_args.extend([
            "-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded",
            "-DCMAKE_POLICY_DEFAULT_CMP0091=NEW",
        ])
    else:
        # Use Ninja on Unix for faster builds
        cmake_args.extend(["-G", "Ninja"])
        # Position independent code for static library
        cmake_args.append("-DCMAKE_POSITION_INDEPENDENT_CODE=ON")

    # Architecture-specific flags
    cmake_args.extend(get_cmake_arch_flags(platform, arch))

    # Configure
    run_command(cmake_args, cwd=cmake_build_dir)

    # Build
    build_cmd = ["cmake", "--build", ".", "--config", config]
    if platform != "win":
        build_cmd.extend(["--parallel"])
    run_command(build_cmd, cwd=cmake_build_dir)

    return cmake_build_dir


def copy_outputs(cmake_build_dir, output_dir, platform, arch, config):
    """Copy built library and headers to output directory."""
    # Determine library name and location
    if platform == "win":
        lib_name = "uv_a.lib"  # libuv static lib on Windows
        lib_src = cmake_build_dir / config / lib_name
        if not lib_src.exists():
            # Try without config subdirectory
            lib_src = cmake_build_dir / lib_name
        lib_dest_name = "libuv.lib"
    else:
        lib_name = "libuv_a.a"  # libuv static lib on Unix
        lib_src = cmake_build_dir / lib_name
        if not lib_src.exists():
            lib_src = cmake_build_dir / "libuv.a"
        lib_dest_name = "libuv.a"

    if not lib_src.exists():
        # Search for the library
        print(f"Looking for library in {cmake_build_dir}...")
        for f in cmake_build_dir.rglob("*.a" if platform != "win" else "*.lib"):
            print(f"  Found: {f}")
            if "uv" in f.name.lower():
                lib_src = f
                break

    if not lib_src.exists():
        print(f"Error: Could not find built library")
        print(f"Searched in: {cmake_build_dir}")
        sys.exit(1)

    # Create output directories
    lib_dir = output_dir / f"libuv-{platform}" / "lib"
    if platform == "mac":
        lib_dir = lib_dir / arch
    lib_dir.mkdir(parents=True, exist_ok=True)

    include_dir = output_dir / "include"
    include_dir.mkdir(parents=True, exist_ok=True)

    # Copy library
    lib_dest = lib_dir / lib_dest_name
    print(f"Copying {lib_src} -> {lib_dest}")
    shutil.copy2(lib_src, lib_dest)

    return lib_dest


def copy_headers(source_dir, output_dir):
    """Copy libuv headers."""
    include_src = source_dir / "include"
    include_dest = output_dir / "include"
    include_dest.mkdir(parents=True, exist_ok=True)

    # Copy all headers
    for header in include_src.glob("*.h"):
        dest = include_dest / header.name
        print(f"Copying header: {header.name}")
        shutil.copy2(header, dest)

    # Copy uv/ subdirectory if it exists
    uv_subdir = include_src / "uv"
    if uv_subdir.exists():
        uv_dest = include_dest / "uv"
        if uv_dest.exists():
            shutil.rmtree(uv_dest)
        shutil.copytree(uv_subdir, uv_dest)
        print(f"Copied uv/ header directory")


def main():
    args = parse_args()

    root_dir = Path(__file__).parent.absolute()
    third_party_dir = root_dir / "third_party"
    build_dir = Path(args.out).absolute()

    # Download libuv source
    source_dir = download_libuv(args.version, third_party_dir)

    archs = [a.strip() for a in args.archs.split(",")]

    for arch in archs:
        print(f"\n{'='*60}")
        print(f"Building libuv for {args.platform} {arch} ({args.config})")
        print(f"{'='*60}\n")

        # Build
        cmake_build_dir = build_libuv(
            source_dir, build_dir, args.platform, arch, args.config
        )

        # Copy outputs
        copy_outputs(cmake_build_dir, build_dir, args.platform, arch, args.config)

    # Copy headers (only once, not per-arch)
    copy_headers(source_dir, build_dir)

    print(f"\n{'='*60}")
    print("Build complete!")
    print(f"Output: {build_dir}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
