#!/usr/bin/env python3

"""
build-webp.py

This script automates the process of building libwebp libraries for various platforms
(macOS, iOS, visionOS, Android, Windows, Linux, and WebAssembly).

libwebp is used for WebP image encoding/decoding, particularly useful for compressed
textures in game engines.

Usage:
    python3 build-webp.py <platform> [options]

For detailed usage instructions, run:
    python3 build-webp.py --help
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Define ANSI color codes
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def colored_print(message, color):
    print(f"{color}{message}{Colors.ENDC}")

# Shared constants
BASE_DIR = Path(__file__).resolve().parent / "build"
WEBP_GIT_URL = "https://chromium.googlesource.com/webm/libwebp.git"
WEBP_SRC_DIR = BASE_DIR / "src" / "libwebp"
TMP_DIR = BASE_DIR / "tmp" / "webp"

# Platform-specific constants
MAC_MIN_VERSION = "10.15"
IOS_MIN_VERSION = "14.0"
VISIONOS_MIN_VERSION = "1.0"
ANDROID_MIN_API = "24"

# Libraries to package
LIBS = {
    "mac": ["libwebp.a", "libwebpdecoder.a", "libwebpdemux.a", "libwebpmux.a", "libsharpyuv.a"],
    "ios": ["libwebp.a", "libwebpdecoder.a", "libwebpdemux.a", "libwebpmux.a", "libsharpyuv.a"],
    "visionos": ["libwebp.a", "libwebpdecoder.a", "libwebpdemux.a", "libwebpmux.a", "libsharpyuv.a"],
    "android": ["libwebp.a", "libwebpdecoder.a", "libwebpdemux.a", "libwebpmux.a", "libsharpyuv.a"],
    "win": ["webp.lib", "webpdecoder.lib", "webpdemux.lib", "webpmux.lib", "sharpyuv.lib"],
    "linux": ["libwebp.a", "libwebpdecoder.a", "libwebpdemux.a", "libwebpmux.a", "libsharpyuv.a"],
    "wasm": ["libwebp.a", "libwebpdecoder.a", "libwebpdemux.a", "libwebpmux.a", "libsharpyuv.a"],
}

# Headers to package
HEADER_DIRS = [
    "src/webp",
    "sharpyuv",
]


class WebPBuildScript:
    def __init__(self):
        self.platform = None
        self.config = "Release"
        self.archs = []
        self.branch = "main"
        self.target = "all"
        self.crt = "static"
        self.ndk_path = None
        self.shallow_clone = False

    def parse_arguments(self):
        parser = argparse.ArgumentParser(description="Build libwebp for multiple platforms")
        parser.add_argument("platform", choices=["mac", "ios", "visionos", "android", "win", "linux", "wasm"],
                           help="Target platform")
        parser.add_argument("-config", choices=["Debug", "Release"], default="Release", help="Build configuration")
        parser.add_argument("-archs", help="Target architectures (comma-separated)")
        parser.add_argument("-branch", help="libwebp Git branch/tag to checkout", default="main")
        parser.add_argument("-target", choices=["device", "simulator", "all"], default="all",
                           help="Build target for iOS/visionOS")
        parser.add_argument("-crt", choices=["static", "dynamic"], default="static",
                           help="Windows CRT linkage: static (/MT) or dynamic (/MD)")
        parser.add_argument("-ndk", help="Path to Android NDK")
        parser.add_argument("--shallow", action="store_true", help="Perform a shallow clone")
        args = parser.parse_args()

        self.platform = args.platform
        self.config = args.config
        self.branch = args.branch
        self.target = args.target
        self.crt = args.crt
        self.ndk_path = args.ndk or os.environ.get("ANDROID_NDK_HOME") or os.environ.get("ANDROID_NDK_ROOT")
        self.shallow_clone = args.shallow

        if args.archs:
            self.archs = args.archs.split(',')
        else:
            self.archs = self.get_default_archs()

        self.validate_archs()

    def get_default_archs(self):
        defaults = {
            "mac": ["universal"],
            "ios": ["arm64"],
            "visionos": ["arm64"],
            "android": ["arm64"],
            "win": ["x64"],
            "linux": ["x64"],
            "wasm": ["wasm32"],
        }
        return defaults.get(self.platform, ["x64"])

    def validate_archs(self):
        valid_archs = {
            "mac": ["x86_64", "arm64", "universal"],
            "ios": ["x86_64", "arm64"],
            "visionos": ["arm64"],
            "android": ["arm64", "arm", "x64", "x86"],
            "win": ["x64", "arm64"],
            "linux": ["x64", "arm64"],
            "wasm": ["wasm32"],
        }
        for arch in self.archs:
            if arch not in valid_archs[self.platform]:
                colored_print(f"Invalid architecture for {self.platform}: {arch}", Colors.FAIL)
                sys.exit(1)

    def get_lib_dir(self):
        crt_suffix = "-md" if self.platform == "win" and self.crt == "dynamic" else ""
        return BASE_DIR / f"webp-{self.platform}{crt_suffix}" / "lib"

    def setup_repo(self):
        colored_print(f"Setting up libwebp repository (branch: {self.branch})...", Colors.OKBLUE)
        if not WEBP_SRC_DIR.exists():
            clone_cmd = ["git", "clone"]
            if self.shallow_clone:
                clone_cmd.extend(["--depth", "1"])
            clone_cmd.extend(["--branch", self.branch, WEBP_GIT_URL, str(WEBP_SRC_DIR)])
            subprocess.run(clone_cmd, check=True)
        else:
            os.chdir(WEBP_SRC_DIR)
            fetch_cmd = ["git", "fetch"]
            if self.shallow_clone:
                fetch_cmd.extend(["--depth", "1"])
            fetch_cmd.extend(["origin", self.branch])
            subprocess.run(fetch_cmd, check=True)
            subprocess.run(["git", "checkout", self.branch], check=True)
            subprocess.run(["git", "reset", "--hard", f"origin/{self.branch}"], check=True)
        colored_print("libwebp repository setup complete.", Colors.OKGREEN)

    def get_cmake_args(self, arch):
        """Get CMake arguments for the current platform/arch."""
        args = [
            "-DCMAKE_BUILD_TYPE=" + self.config,
            "-DWEBP_BUILD_ANIM_UTILS=OFF",
            "-DWEBP_BUILD_CWEBP=OFF",
            "-DWEBP_BUILD_DWEBP=OFF",
            "-DWEBP_BUILD_GIF2WEBP=OFF",
            "-DWEBP_BUILD_IMG2WEBP=OFF",
            "-DWEBP_BUILD_VWEBP=OFF",
            "-DWEBP_BUILD_WEBPINFO=OFF",
            "-DWEBP_BUILD_WEBPMUX=OFF",
            "-DWEBP_BUILD_EXTRAS=OFF",
            "-DBUILD_SHARED_LIBS=OFF",
        ]

        if self.platform == "mac":
            args.extend([
                f"-DCMAKE_OSX_DEPLOYMENT_TARGET={MAC_MIN_VERSION}",
                f"-DCMAKE_OSX_ARCHITECTURES={arch}",
            ])
        elif self.platform == "ios":
            is_simulator = (arch == "x86_64") or (self.target == "simulator")
            sdk = "iphonesimulator" if is_simulator else "iphoneos"
            sdk_path = subprocess.run(
                ["xcrun", "--sdk", sdk, "--show-sdk-path"],
                capture_output=True, text=True, check=True
            ).stdout.strip()
            args.extend([
                "-DCMAKE_SYSTEM_NAME=iOS",
                f"-DCMAKE_OSX_DEPLOYMENT_TARGET={IOS_MIN_VERSION}",
                f"-DCMAKE_OSX_ARCHITECTURES={arch}",
                f"-DCMAKE_OSX_SYSROOT={sdk_path}",
            ])
            if is_simulator:
                args.append("-DCMAKE_OSX_SIMULATOR=ON")
        elif self.platform == "visionos":
            is_simulator = (self.target == "simulator")
            sdk = "xrsimulator" if is_simulator else "xros"
            sdk_path = subprocess.run(
                ["xcrun", "--sdk", sdk, "--show-sdk-path"],
                capture_output=True, text=True, check=True
            ).stdout.strip()
            target_suffix = "-simulator" if is_simulator else ""
            args.extend([
                "-DCMAKE_SYSTEM_NAME=visionOS",
                f"-DCMAKE_OSX_DEPLOYMENT_TARGET={VISIONOS_MIN_VERSION}",
                "-DCMAKE_OSX_ARCHITECTURES=arm64",
                f"-DCMAKE_OSX_SYSROOT={sdk_path}",
                f"-DCMAKE_C_FLAGS=-target arm64-apple-xros{VISIONOS_MIN_VERSION}{target_suffix}",
                f"-DCMAKE_CXX_FLAGS=-target arm64-apple-xros{VISIONOS_MIN_VERSION}{target_suffix}",
            ])
        elif self.platform == "android":
            if not self.ndk_path:
                colored_print("Error: Android NDK path required. Use -ndk or set ANDROID_NDK_HOME", Colors.FAIL)
                sys.exit(1)
            arch_map = {"arm64": "arm64-v8a", "arm": "armeabi-v7a", "x64": "x86_64", "x86": "x86"}
            args.extend([
                "-DCMAKE_SYSTEM_NAME=Android",
                f"-DCMAKE_ANDROID_NDK={self.ndk_path}",
                f"-DCMAKE_ANDROID_ARCH_ABI={arch_map.get(arch, arch)}",
                f"-DCMAKE_ANDROID_API={ANDROID_MIN_API}",
                "-DCMAKE_ANDROID_STL_TYPE=c++_static",
            ])
        elif self.platform == "win":
            crt_flag = "/MD" if self.crt == "dynamic" else "/MT"
            if self.config == "Debug":
                crt_flag += "d"
            args.extend([
                "-G", "Ninja",
                f"-DCMAKE_C_FLAGS_RELEASE={crt_flag}",
                f"-DCMAKE_CXX_FLAGS_RELEASE={crt_flag}",
                f"-DCMAKE_C_FLAGS_DEBUG={crt_flag}",
                f"-DCMAKE_CXX_FLAGS_DEBUG={crt_flag}",
                "-DCMAKE_MSVC_RUNTIME_LIBRARY=" +
                    ("MultiThreadedDLL" if self.crt == "dynamic" else "MultiThreaded") +
                    ("Debug" if self.config == "Debug" else ""),
            ])
        elif self.platform == "linux":
            args.extend([
                "-G", "Ninja",
            ])
        elif self.platform == "wasm":
            # Emscripten toolchain
            emsdk_path = os.environ.get("EMSDK")
            if emsdk_path:
                toolchain = Path(emsdk_path) / "upstream" / "emscripten" / "cmake" / "Modules" / "Platform" / "Emscripten.cmake"
                if toolchain.exists():
                    args.append(f"-DCMAKE_TOOLCHAIN_FILE={toolchain}")
            args.extend([
                "-G", "Ninja",
                "-DCMAKE_SYSTEM_NAME=Emscripten",
            ])

        return args

    def build(self, arch):
        """Build libwebp for a specific architecture."""
        build_dir = TMP_DIR / f"{self.platform}_{self.config}_{arch}"
        build_dir.mkdir(parents=True, exist_ok=True)

        colored_print(f"Building libwebp for {self.platform} {arch}...", Colors.OKBLUE)

        cmake_args = self.get_cmake_args(arch)
        cmake_cmd = ["cmake", "-S", str(WEBP_SRC_DIR), "-B", str(build_dir)] + cmake_args

        colored_print(f"CMake command: {' '.join(cmake_cmd)}", Colors.OKCYAN)
        subprocess.run(cmake_cmd, check=True)

        # Build
        build_cmd = ["cmake", "--build", str(build_dir), "--config", self.config, "-j"]
        subprocess.run(build_cmd, check=True)

        colored_print(f"Successfully built libwebp for {self.platform} {arch}", Colors.OKGREEN)

    def move_libs(self, arch):
        """Move built libraries to output directory."""
        build_dir = TMP_DIR / f"{self.platform}_{self.config}_{arch}"
        lib_dir = self.get_lib_dir()

        if self.platform in ["ios", "visionos"]:
            is_simulator = (arch == "x86_64") or (self.target == "simulator")
            target_prefix = "simulator" if is_simulator else "device"
            dest_dir = lib_dir / self.config / f"{target_prefix}-{arch}"
        elif self.platform == "mac" and arch == "universal":
            dest_dir = lib_dir / self.config
        else:
            dest_dir = lib_dir / self.config / arch

        dest_dir.mkdir(parents=True, exist_ok=True)

        # Find and copy libraries
        for lib in LIBS[self.platform]:
            # Search in common locations
            possible_paths = [
                build_dir / lib,
                build_dir / "src" / lib,
                build_dir / "sharpyuv" / lib,
                build_dir / self.config / lib,
            ]

            # Also check for .a vs .lib naming
            lib_base = lib.replace(".lib", "").replace("lib", "", 1).replace(".a", "")
            possible_paths.extend([
                build_dir / f"lib{lib_base}.a",
                build_dir / f"{lib_base}.lib",
                build_dir / "src" / f"lib{lib_base}.a",
                build_dir / "sharpyuv" / f"lib{lib_base}.a",
            ])

            found = False
            for src_path in possible_paths:
                if src_path.exists():
                    shutil.copy2(str(src_path), str(dest_dir / lib))
                    colored_print(f"Copied {lib} to {dest_dir}", Colors.OKGREEN)
                    found = True
                    break

            if not found:
                # Try recursive search
                for found_lib in build_dir.rglob(f"*{lib_base}*"):
                    if found_lib.suffix in [".a", ".lib"] and found_lib.is_file():
                        shutil.copy2(str(found_lib), str(dest_dir / lib))
                        colored_print(f"Copied {found_lib.name} as {lib} to {dest_dir}", Colors.OKGREEN)
                        found = True
                        break

            if not found:
                colored_print(f"Warning: {lib} not found in {build_dir}", Colors.WARNING)

    def create_universal_binary(self):
        """Create universal binary for macOS."""
        colored_print("Creating universal binaries...", Colors.OKBLUE)
        lib_dir = self.get_lib_dir()
        dest_dir = lib_dir / self.config
        dest_dir.mkdir(parents=True, exist_ok=True)

        for lib in LIBS["mac"]:
            input_libs = []
            for arch in ["x86_64", "arm64"]:
                lib_path = lib_dir / self.config / arch / lib
                if lib_path.exists():
                    input_libs.append(str(lib_path))

            if len(input_libs) == 2:
                output_lib = str(dest_dir / lib)
                subprocess.run(["lipo", "-create"] + input_libs + ["-output", output_lib], check=True)
                colored_print(f"Created universal: {lib}", Colors.OKGREEN)
            elif len(input_libs) == 1:
                shutil.copy2(input_libs[0], str(dest_dir / lib))
                colored_print(f"Single arch copy: {lib}", Colors.WARNING)

        # Cleanup arch-specific directories
        shutil.rmtree(lib_dir / self.config / "x86_64", ignore_errors=True)
        shutil.rmtree(lib_dir / self.config / "arm64", ignore_errors=True)

    def package_headers(self):
        """Package headers to output directory."""
        dest_dir = BASE_DIR / "include" / "webp"
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Copy main webp headers
        webp_include = WEBP_SRC_DIR / "src" / "webp"
        if webp_include.exists():
            for header in webp_include.glob("*.h"):
                shutil.copy2(str(header), str(dest_dir / header.name))
                colored_print(f"Copied header: {header.name}", Colors.OKCYAN)

        # Copy sharpyuv headers
        sharpyuv_dir = BASE_DIR / "include" / "sharpyuv"
        sharpyuv_dir.mkdir(parents=True, exist_ok=True)
        sharpyuv_src = WEBP_SRC_DIR / "sharpyuv"
        if sharpyuv_src.exists():
            for header in sharpyuv_src.glob("*.h"):
                shutil.copy2(str(header), str(sharpyuv_dir / header.name))
                colored_print(f"Copied header: sharpyuv/{header.name}", Colors.OKCYAN)

    def run(self):
        self.parse_arguments()
        self.setup_repo()

        if "universal" in self.archs:
            self.archs = ["x86_64", "arm64"]
            build_universal = True
        else:
            build_universal = False

        for arch in self.archs:
            self.build(arch)
            self.move_libs(arch)

        if self.platform == "mac" and build_universal:
            self.create_universal_binary()

        self.package_headers()

        colored_print(f"Build completed for {self.platform} {self.config}", Colors.OKGREEN)


if __name__ == "__main__":
    WebPBuildScript().run()
