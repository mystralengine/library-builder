#!/usr/bin/env python3
"""
Build sherpa-onnx static libraries for multiple platforms.

sherpa-onnx provides speech synthesis (TTS) and recognition in C/C++.
Used for KittenTTS voice synthesis without Python dependencies.

Source: https://github.com/k2-fsa/sherpa-onnx
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

SHERPAONNX_VERSION = "v1.12.30"
SHERPAONNX_REPO = "https://github.com/k2-fsa/sherpa-onnx.git"


def parse_args():
    parser = argparse.ArgumentParser(description="Build sherpa-onnx static libraries")
    parser.add_argument("platform", choices=["mac", "ios", "android", "linux", "win"],
                        help="Target platform")
    parser.add_argument("-archs", help="Target architectures (comma separated)", default=None)
    parser.add_argument("-config", choices=["Release", "Debug"], default="Release")
    parser.add_argument("-out", help="Output directory", default="build")
    parser.add_argument("-version", help="sherpa-onnx version/tag", default=SHERPAONNX_VERSION)
    parser.add_argument("-ndk", help="Android NDK path", default=None)
    return parser.parse_args()


def run_command(cmd, cwd=None, env=None, shell=False):
    print(f"Running: {cmd if shell else ' '.join(cmd)}")
    try:
        subprocess.check_call(cmd, cwd=cwd, env=env, shell=shell)
    except subprocess.CalledProcessError as e:
        print(f"Command failed with exit code {e.returncode}")
        sys.exit(1)


def download_source(version, dest_dir):
    """Clone sherpa-onnx source (with submodules)."""
    extract_dir = dest_dir / f"sherpa-onnx-{version}"

    if extract_dir.exists():
        print(f"sherpa-onnx source already exists at {extract_dir}")
        return extract_dir

    dest_dir.mkdir(parents=True, exist_ok=True)

    print(f"Cloning sherpa-onnx {version}...")
    run_command([
        "git", "clone", "--depth", "1", "--recurse-submodules", "--shallow-submodules",
        "--branch", version, SHERPAONNX_REPO, str(extract_dir)
    ])

    return extract_dir


def get_default_arch(platform):
    """Return default architecture for a given platform."""
    defaults = {
        "mac": "arm64",
        "ios": "arm64",
        "android": "arm64",
        "linux": "x64",
        "win": "x64",
    }
    return defaults[platform]


def get_ndk_path(args_ndk):
    """Resolve Android NDK path."""
    if args_ndk:
        return args_ndk
    for env_var in ("ANDROID_NDK_HOME", "ANDROID_NDK_ROOT", "ANDROID_NDK"):
        val = os.environ.get(env_var)
        if val:
            return val
    print("Error: Android NDK not found. Set ANDROID_NDK_HOME or use -ndk flag.")
    sys.exit(1)


def get_cmake_flags(platform, arch, config, ndk_path=None):
    """Get CMake configure flags for the target."""
    flags = [
        f"-DCMAKE_BUILD_TYPE={config}",
        "-DBUILD_SHARED_LIBS=OFF",
        # Enable TTS with C API only
        "-DSHERPA_ONNX_ENABLE_TTS=ON",
        "-DSHERPA_ONNX_ENABLE_C_API=ON",
        # Disable everything we don't need
        "-DSHERPA_ONNX_ENABLE_BINARY=OFF",
        "-DSHERPA_ONNX_BUILD_C_API_EXAMPLES=OFF",
        "-DSHERPA_ONNX_ENABLE_PYTHON=OFF",
        "-DSHERPA_ONNX_ENABLE_TESTS=OFF",
        "-DSHERPA_ONNX_ENABLE_CHECK=OFF",
        "-DSHERPA_ONNX_ENABLE_PORTAUDIO=OFF",
        "-DSHERPA_ONNX_ENABLE_JNI=OFF",
        "-DSHERPA_ONNX_ENABLE_WEBSOCKET=OFF",
        "-DSHERPA_ONNX_ENABLE_GPU=OFF",
        # Disable piper-phonemize extras
        "-DBUILD_PIPER_PHONMIZE_EXE=OFF",
        "-DBUILD_PIPER_PHONMIZE_TESTS=OFF",
        # Disable espeak-ng extras
        "-DBUILD_ESPEAK_NG_EXE=OFF",
        "-DBUILD_ESPEAK_NG_TESTS=OFF",
    ]

    if platform == "mac":
        if arch == "arm64":
            flags.append("-DCMAKE_OSX_ARCHITECTURES=arm64")
        elif arch in ("x64", "x86_64"):
            flags.append("-DCMAKE_OSX_ARCHITECTURES=x86_64")
        flags.append("-DCMAKE_OSX_DEPLOYMENT_TARGET=13.0")
        flags.extend(["-G", "Ninja"])
        flags.append("-DCMAKE_POSITION_INDEPENDENT_CODE=ON")

    elif platform == "ios":
        flags.append("-DCMAKE_SYSTEM_NAME=iOS")
        flags.append("-DCMAKE_OSX_DEPLOYMENT_TARGET=16.0")
        if arch == "arm64":
            flags.append("-DCMAKE_OSX_ARCHITECTURES=arm64")
        flags.extend(["-G", "Ninja"])
        flags.append("-DCMAKE_POSITION_INDEPENDENT_CODE=ON")

    elif platform == "android":
        ndk = get_ndk_path(ndk_path)
        toolchain = os.path.join(ndk, "build", "cmake", "android.toolchain.cmake")
        flags.append(f"-DCMAKE_TOOLCHAIN_FILE={toolchain}")
        flags.append("-DANDROID_PLATFORM=android-28")
        abi_map = {
            "arm64": "arm64-v8a",
            "arm": "armeabi-v7a",
            "x64": "x86_64",
            "x86": "x86",
        }
        abi = abi_map.get(arch, "arm64-v8a")
        flags.append(f"-DANDROID_ABI={abi}")
        flags.extend(["-G", "Ninja"])

    elif platform == "linux":
        flags.extend(["-G", "Ninja"])
        flags.append("-DCMAKE_POSITION_INDEPENDENT_CODE=ON")

    elif platform == "win":
        if arch in ("x64", "x86_64"):
            flags.extend(["-A", "x64"])
        elif arch == "x86":
            flags.extend(["-A", "Win32"])
        # Static CRT
        flags.append("-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded")
        flags.append("-DCMAKE_POLICY_DEFAULT_CMP0091=NEW")

    return flags


def build_sherpaonnx(source_dir, build_dir, platform, arch, config, ndk_path=None):
    """Build sherpa-onnx using CMake."""
    cmake_build_dir = build_dir / f"cmake-build-sherpaonnx-{platform}-{arch}"
    cmake_build_dir.mkdir(parents=True, exist_ok=True)

    cmake_args = ["cmake", str(source_dir)]
    cmake_args.extend(get_cmake_flags(platform, arch, config, ndk_path))

    # Configure
    run_command(cmake_args, cwd=cmake_build_dir)

    # Build
    build_cmd = ["cmake", "--build", ".", "--config", config]
    if platform != "win":
        build_cmd.extend(["--parallel"])
    run_command(build_cmd, cwd=cmake_build_dir)

    return cmake_build_dir


def find_libraries(cmake_build_dir, platform):
    """Find all built static libraries."""
    ext = "*.lib" if platform == "win" else "*.a"
    libs = {}

    # Libraries produced by sherpa-onnx TTS build
    wanted = [
        "sherpa-onnx-c-api", "sherpa-onnx-core",
        "kaldi-decoder-core", "sherpa-onnx-kaldifst-core",
        "sherpa-onnx-fst", "sherpa-onnx-fstfar",
        "kaldi-native-fbank-core", "kissfft",
        "ssentencepiece_core", "piper_phonemize",
        "espeak-ng", "ucd", "onnxruntime",
    ]

    for f in cmake_build_dir.rglob(ext):
        name = f.stem.lower()
        # Remove 'lib' prefix on Unix
        if name.startswith("lib"):
            name = name[3:]
        # Check if this is a library we want
        for w in wanted:
            if w.lower() in name:
                libs[f.name] = f
                break

    return libs


def copy_outputs(cmake_build_dir, output_dir, platform, arch, config):
    """Copy built libraries to output directory."""
    libs = find_libraries(cmake_build_dir, platform)

    if not libs:
        print(f"Error: No libraries found in {cmake_build_dir}")
        ext = "*.lib" if platform == "win" else "*.a"
        for f in cmake_build_dir.rglob(ext):
            print(f"  Found: {f}")
        sys.exit(1)

    # Create output directory
    lib_dir = output_dir / f"sherpaonnx-{platform}" / "lib"
    if platform in ("mac", "ios"):
        lib_dir = lib_dir / arch
    lib_dir.mkdir(parents=True, exist_ok=True)

    for lib_name, lib_path in libs.items():
        dest = lib_dir / lib_name
        print(f"Copying {lib_path} -> {dest}")
        shutil.copy2(lib_path, dest)

    return lib_dir


def copy_headers(source_dir, output_dir):
    """Copy sherpa-onnx public C API header."""
    include_dest = output_dir / "include" / "sherpaonnx"
    include_dest.mkdir(parents=True, exist_ok=True)

    header = source_dir / "sherpa-onnx" / "c-api" / "c-api.h"
    if header.exists():
        dest = include_dest / "c-api.h"
        print(f"Copying header: c-api.h")
        shutil.copy2(header, dest)
    else:
        print(f"Warning: C API header not found at {header}")


def main():
    args = parse_args()

    root_dir = Path(__file__).parent.absolute()
    third_party_dir = root_dir / "third_party"
    build_dir = Path(args.out).absolute()

    # Download source
    source_dir = download_source(args.version, third_party_dir)

    arch = args.archs or get_default_arch(args.platform)
    archs = [a.strip() for a in arch.split(",")]

    for arch in archs:
        print(f"\n{'='*60}")
        print(f"Building sherpa-onnx for {args.platform} {arch} ({args.config})")
        print(f"{'='*60}\n")

        cmake_build_dir = build_sherpaonnx(
            source_dir, build_dir, args.platform, arch, args.config,
            ndk_path=args.ndk,
        )

        copy_outputs(cmake_build_dir, build_dir, args.platform, arch, args.config)

    # Copy headers once
    copy_headers(source_dir, build_dir)

    print(f"\n{'='*60}")
    print("Build complete!")
    print(f"Output: {build_dir}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
