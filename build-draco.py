#!/usr/bin/env python3
"""
Build Draco static library for multiple platforms.

Draco is a library for compressing and decompressing 3D geometric meshes
and point clouds. Used by glTF KHR_draco_mesh_compression extension.

Source: https://github.com/google/draco
"""

import argparse
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

DRACO_VERSION = "1.5.7"
DRACO_URL = f"https://github.com/google/draco/archive/refs/tags/{DRACO_VERSION}.zip"


def parse_args():
    parser = argparse.ArgumentParser(description="Build Draco static library")
    parser.add_argument("platform", choices=["mac", "linux", "win"], help="Target platform")
    parser.add_argument("-archs", help="Target architectures (comma separated)", default="x64")
    parser.add_argument("-config", choices=["Release", "Debug"], default="Release")
    parser.add_argument("-out", help="Output directory", default="build")
    parser.add_argument("-version", help="Draco version", default=DRACO_VERSION)
    return parser.parse_args()


def run_command(cmd, cwd=None, env=None, shell=False):
    print(f"Running: {cmd if shell else ' '.join(cmd)}")
    try:
        subprocess.check_call(cmd, cwd=cwd, env=env, shell=shell)
    except subprocess.CalledProcessError as e:
        print(f"Command failed with exit code {e.returncode}")
        sys.exit(1)


def download_draco(version, dest_dir):
    """Download and extract Draco source."""
    url = f"https://github.com/google/draco/archive/refs/tags/{version}.zip"
    zip_path = dest_dir / f"draco-{version}.zip"
    extract_dir = dest_dir / f"draco-{version}"

    if extract_dir.exists():
        print(f"Draco source already exists at {extract_dir}")
        return extract_dir

    dest_dir.mkdir(parents=True, exist_ok=True)

    print(f"Downloading Draco v{version}...")
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


def build_draco(source_dir, build_dir, platform, arch, config):
    """Build Draco using CMake."""
    cmake_build_dir = build_dir / f"cmake-build-{platform}-{arch}"
    cmake_build_dir.mkdir(parents=True, exist_ok=True)

    # Base CMake arguments
    cmake_args = [
        "cmake",
        str(source_dir),
        f"-DCMAKE_BUILD_TYPE={config}",
        # Enable mesh compression (core feature for glTF)
        "-DDRACO_MESH_COMPRESSION=ON",
        "-DDRACO_POINT_CLOUD_COMPRESSION=ON",
        # Disable features we don't need
        "-DDRACO_JAVASCRIPT_GLUE=OFF",
        "-DDRACO_WASM=OFF",
        "-DDRACO_ANIMATION_ENCODING=OFF",
        "-DDRACO_TRANSCODER=OFF",
        "-DDRACO_TESTS=OFF",
        "-DDRACO_BUILD_TOOLS=OFF",
        "-DBUILD_SHARED_LIBS=OFF",
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
        lib_name = "draco.lib"
        # Windows: library may be in config subdirectory
        lib_src = cmake_build_dir / config / lib_name
        if not lib_src.exists():
            lib_src = cmake_build_dir / lib_name
        lib_dest_name = "draco.lib"
    else:
        lib_name = "libdraco.a"
        lib_src = cmake_build_dir / lib_name
        lib_dest_name = "libdraco.a"

    if not lib_src.exists():
        # Search for the library
        print(f"Looking for library in {cmake_build_dir}...")
        ext = "*.lib" if platform == "win" else "*.a"
        for f in cmake_build_dir.rglob(ext):
            print(f"  Found: {f}")
            if "draco" in f.name.lower() and "encoder" not in f.name.lower():
                lib_src = f
                break

    if not lib_src.exists():
        print(f"Error: Could not find built library")
        print(f"Searched in: {cmake_build_dir}")
        sys.exit(1)

    # Create output directories
    lib_dir = output_dir / f"draco-{platform}" / "lib"
    if platform == "mac":
        lib_dir = lib_dir / arch
    lib_dir.mkdir(parents=True, exist_ok=True)

    # Copy library
    lib_dest = lib_dir / lib_dest_name
    print(f"Copying {lib_src} -> {lib_dest}")
    shutil.copy2(lib_src, lib_dest)

    return lib_dest


def copy_headers(source_dir, cmake_build_dir, output_dir):
    """Copy Draco headers including CMake-generated draco_features.h."""
    include_dest = output_dir / "include" / "draco"
    include_dest.mkdir(parents=True, exist_ok=True)

    # Copy public API headers from source
    src_include = source_dir / "src" / "draco"

    # Key header directories needed for decoding
    header_dirs = [
        "compression",
        "core",
        "mesh",
        "point_cloud",
        "attributes",
        "metadata",
    ]

    for hdir in header_dirs:
        src_dir = src_include / hdir
        if src_dir.exists():
            dest_dir = include_dest / hdir
            dest_dir.mkdir(parents=True, exist_ok=True)
            for header in src_dir.glob("*.h"):
                dest = dest_dir / header.name
                shutil.copy2(header, dest)
                print(f"Copied header: draco/{hdir}/{header.name}")

    # Copy top-level draco headers
    for header in src_include.glob("*.h"):
        dest = include_dest / header.name
        shutil.copy2(header, dest)
        print(f"Copied header: draco/{header.name}")

    # Copy CMake-generated draco_features.h (critical - defines feature macros)
    features_header = cmake_build_dir / "draco" / "draco_features.h"
    if not features_header.exists():
        # Try alternative paths
        for candidate in cmake_build_dir.rglob("draco_features.h"):
            features_header = candidate
            break

    if features_header.exists():
        dest = include_dest / "draco_features.h"
        shutil.copy2(features_header, dest)
        print(f"Copied generated header: draco/draco_features.h")
    else:
        print("WARNING: draco_features.h not found - build may fail without it")


def main():
    args = parse_args()

    root_dir = Path(__file__).parent.absolute()
    third_party_dir = root_dir / "third_party"
    build_dir = Path(args.out).absolute()

    # Download Draco source
    source_dir = download_draco(args.version, third_party_dir)

    archs = [a.strip() for a in args.archs.split(",")]

    cmake_build_dir = None
    for arch in archs:
        print(f"\n{'='*60}")
        print(f"Building Draco for {args.platform} {arch} ({args.config})")
        print(f"{'='*60}\n")

        # Build
        cmake_build_dir = build_draco(
            source_dir, build_dir, args.platform, arch, args.config
        )

        # Copy outputs
        copy_outputs(cmake_build_dir, build_dir, args.platform, arch, args.config)

    # Copy headers (only once, not per-arch) — needs cmake_build_dir for generated headers
    if cmake_build_dir:
        copy_headers(source_dir, cmake_build_dir, build_dir)

    print(f"\n{'='*60}")
    print("Build complete!")
    print(f"Output: {build_dir}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
