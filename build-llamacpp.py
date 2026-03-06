#!/usr/bin/env python3
"""
Build llama.cpp static libraries for multiple platforms.

llama.cpp provides LLM inference in C/C++. Used by PixieAI for local
text generation, chat, and tool-use capabilities.

Source: https://github.com/ggerganov/llama.cpp
"""

import argparse
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

LLAMACPP_VERSION = "b5604"
LLAMACPP_URL = f"https://github.com/ggerganov/llama.cpp/archive/refs/tags/{LLAMACPP_VERSION}.zip"


def parse_args():
    parser = argparse.ArgumentParser(description="Build llama.cpp static libraries")
    parser.add_argument("platform", choices=["mac", "ios", "android", "linux", "win"],
                        help="Target platform")
    parser.add_argument("-archs", help="Target architectures (comma separated)", default=None)
    parser.add_argument("-config", choices=["Release", "Debug"], default="Release")
    parser.add_argument("-out", help="Output directory", default="build")
    parser.add_argument("-version", help="llama.cpp version/tag", default=LLAMACPP_VERSION)
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
    """Download and extract llama.cpp source."""
    url = f"https://github.com/ggerganov/llama.cpp/archive/refs/tags/{version}.zip"
    zip_path = dest_dir / f"llama.cpp-{version}.zip"
    extract_dir = dest_dir / f"llama.cpp-{version}"

    if extract_dir.exists():
        print(f"llama.cpp source already exists at {extract_dir}")
        return extract_dir

    dest_dir.mkdir(parents=True, exist_ok=True)

    print(f"Downloading llama.cpp {version}...")
    urllib.request.urlretrieve(url, zip_path)

    print(f"Extracting to {dest_dir}...")
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(dest_dir)

    zip_path.unlink()
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
        "-DLLAMA_BUILD_TESTS=OFF",
        "-DLLAMA_BUILD_EXAMPLES=OFF",
        "-DLLAMA_BUILD_SERVER=OFF",
        "-DLLAMA_CURL=OFF",
    ]

    if platform == "mac":
        if arch == "arm64":
            flags.append("-DCMAKE_OSX_ARCHITECTURES=arm64")
        elif arch in ("x64", "x86_64"):
            flags.append("-DCMAKE_OSX_ARCHITECTURES=x86_64")
        flags.append("-DCMAKE_OSX_DEPLOYMENT_TARGET=13.0")
        # Disable native CPU detection to avoid i8mm intrinsics on CI runners
        flags.append("-DGGML_NATIVE=OFF")
        # Enable Metal on macOS
        flags.append("-DGGML_METAL=ON")
        flags.append("-DGGML_METAL_EMBED_LIBRARY=ON")
        # Use Ninja
        flags.extend(["-G", "Ninja"])
        flags.append("-DCMAKE_POSITION_INDEPENDENT_CODE=ON")

    elif platform == "ios":
        flags.append("-DCMAKE_SYSTEM_NAME=iOS")
        flags.append("-DCMAKE_OSX_DEPLOYMENT_TARGET=16.0")
        if arch == "arm64":
            flags.append("-DCMAKE_OSX_ARCHITECTURES=arm64")
        # Enable Metal on iOS
        flags.append("-DGGML_METAL=ON")
        flags.append("-DGGML_METAL_EMBED_LIBRARY=ON")
        # Disable features that don't work on iOS
        flags.append("-DGGML_OPENMP=OFF")
        # Disable tools to avoid BUNDLE DESTINATION install errors
        flags.append("-DLLAMA_BUILD_TOOLS=OFF")
        flags.extend(["-G", "Ninja"])
        flags.append("-DCMAKE_POSITION_INDEPENDENT_CODE=ON")

    elif platform == "android":
        ndk = get_ndk_path(ndk_path)
        toolchain = os.path.join(ndk, "build", "cmake", "android.toolchain.cmake")
        flags.append(f"-DCMAKE_TOOLCHAIN_FILE={toolchain}")
        flags.append("-DANDROID_PLATFORM=android-28")
        # Map arch to Android ABI
        abi_map = {
            "arm64": "arm64-v8a",
            "arm": "armeabi-v7a",
            "x64": "x86_64",
            "x86": "x86",
        }
        abi = abi_map.get(arch, "arm64-v8a")
        flags.append(f"-DANDROID_ABI={abi}")
        # CPU-only on Android (Vulkan requires glslc which CI runners lack)
        flags.append("-DGGML_VULKAN=OFF")
        flags.append("-DGGML_OPENMP=OFF")
        flags.extend(["-G", "Ninja"])

    elif platform == "linux":
        flags.extend(["-G", "Ninja"])
        flags.append("-DCMAKE_POSITION_INDEPENDENT_CODE=ON")
        # CPU-only by default; CUDA can be enabled with -DGGML_CUDA=ON
        flags.append("-DGGML_CUDA=OFF")

    elif platform == "win":
        if arch in ("x64", "x86_64"):
            flags.extend(["-A", "x64"])
        elif arch == "x86":
            flags.extend(["-A", "Win32"])
        # Static CRT
        flags.append("-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded")
        flags.append("-DCMAKE_POLICY_DEFAULT_CMP0091=NEW")

    return flags


def build_llamacpp(source_dir, build_dir, platform, arch, config, ndk_path=None):
    """Build llama.cpp using CMake."""
    cmake_build_dir = build_dir / f"cmake-build-llamacpp-{platform}-{arch}"
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

    # Key libraries we want from llama.cpp
    wanted = ["llama", "ggml", "common"]

    for f in cmake_build_dir.rglob(ext):
        name = f.stem.lower()
        # Remove 'lib' prefix on Unix
        if name.startswith("lib"):
            name = name[3:]
        # Check if this is a library we want
        for w in wanted:
            if w in name:
                libs[f.name] = f
                break

    return libs


def copy_outputs(cmake_build_dir, output_dir, platform, arch, config):
    """Copy built libraries to output directory."""
    libs = find_libraries(cmake_build_dir, platform)

    if not libs:
        print(f"Error: No libraries found in {cmake_build_dir}")
        # List what's there for debugging
        ext = "*.lib" if platform == "win" else "*.a"
        for f in cmake_build_dir.rglob(ext):
            print(f"  Found: {f}")
        sys.exit(1)

    # Create output directory
    lib_dir = output_dir / f"llamacpp-{platform}" / "lib"
    if platform in ("mac", "ios"):
        lib_dir = lib_dir / arch
    lib_dir.mkdir(parents=True, exist_ok=True)

    for lib_name, lib_path in libs.items():
        dest = lib_dir / lib_name
        print(f"Copying {lib_path} -> {dest}")
        shutil.copy2(lib_path, dest)

    return lib_dir


def copy_headers(source_dir, output_dir):
    """Copy llama.cpp public headers."""
    include_dest = output_dir / "include" / "llamacpp"
    include_dest.mkdir(parents=True, exist_ok=True)

    # Main public headers
    public_headers = [
        "include/llama.h",
        "include/llama-cpp.h",
    ]

    for header_rel in public_headers:
        header = source_dir / header_rel
        if header.exists():
            dest = include_dest / header.name
            print(f"Copying header: {header.name}")
            shutil.copy2(header, dest)

    # ggml headers
    ggml_include = source_dir / "ggml" / "include"
    if ggml_include.exists():
        ggml_dest = include_dest / "ggml"
        ggml_dest.mkdir(parents=True, exist_ok=True)
        for header in ggml_include.glob("*.h"):
            dest = ggml_dest / header.name
            print(f"Copying header: ggml/{header.name}")
            shutil.copy2(header, dest)

    # Also check top-level include for ggml headers
    top_include = source_dir / "include"
    if top_include.exists():
        for header in top_include.glob("ggml*.h"):
            dest = include_dest / "ggml" / header.name
            (include_dest / "ggml").mkdir(parents=True, exist_ok=True)
            print(f"Copying header: ggml/{header.name}")
            shutil.copy2(header, dest)


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
        print(f"Building llama.cpp for {args.platform} {arch} ({args.config})")
        print(f"{'='*60}\n")

        cmake_build_dir = build_llamacpp(
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
