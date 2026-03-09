#!/usr/bin/env python3
"""
Build qwen3-asr-swift (Qwen3 Speech) static libraries for macOS.

qwen3-asr-swift provides MLX-based speech models for Apple Silicon:
- Qwen3-ASR: Speech-to-text (52 languages)
- Qwen3-TTS: Text-to-speech (highest quality, voice cloning)
- CosyVoice3: Text-to-speech (streaming, low latency)
- PersonaPlex: Speech-to-speech (full-duplex, 7B)
- Parakeet: Speech-to-text (CoreML Neural Engine)
- SpeechVAD: Voice activity detection
- SpeechEnhancement: Noise suppression

Source: https://github.com/ivan-digital/qwen3-asr-swift
Requires: macOS 14+, Apple Silicon, Xcode with Metal Toolchain
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

QWEN3SPEECH_VERSION = "main"
QWEN3SPEECH_REPO = "https://github.com/ivan-digital/qwen3-asr-swift.git"

# Swift modules to package from the build
WANTED_MODULES = [
    "AudioCommon",
    "CosyVoiceTTS",
    "PersonaPlex",
    "ParakeetASR",
    "Qwen3ASR",
    "Qwen3TTS",
    "SpeechEnhancement",
    "SpeechVAD",
]

# All modules needed (including transitive dependencies like MLX, Hub, etc.)
# These are archived into static libraries from SwiftPM's .o files
ALL_MODULES_TO_ARCHIVE = WANTED_MODULES + [
    # MLX framework
    "MLX", "MLXNN", "MLXFast", "MLXLinalg", "MLXFFT", "MLXRandom", "MLXOptimizers",
    "Cmlx",
    # HuggingFace
    "Hub", "Tokenizers", "Generation", "Models", "Jinja",
    # Other dependencies used by speech modules
    "yyjson",
]


def parse_args():
    parser = argparse.ArgumentParser(description="Build qwen3-asr-swift static libraries")
    parser.add_argument("platform", choices=["mac"],
                        help="Target platform (macOS only — requires Apple Silicon + Metal)")
    parser.add_argument("-archs", help="Target architecture (default: arm64)", default="arm64")
    parser.add_argument("-config", choices=["release", "debug"], default="release")
    parser.add_argument("-out", help="Output directory", default="build")
    parser.add_argument("-version", help="Git branch/tag/commit", default=QWEN3SPEECH_VERSION)
    parser.add_argument("--local-source", help="Use local source directory instead of cloning",
                        default=None)
    return parser.parse_args()


def run_command(cmd, cwd=None, env=None, shell=False):
    print(f"Running: {cmd if shell else ' '.join(cmd)}")
    try:
        subprocess.check_call(cmd, cwd=cwd, env=env, shell=shell)
    except subprocess.CalledProcessError as e:
        print(f"Command failed with exit code {e.returncode}")
        sys.exit(1)


def clone_source(version, dest_dir):
    """Clone qwen3-asr-swift at the specified version."""
    source_dir = dest_dir / f"qwen3-asr-swift-{version}"

    if source_dir.exists():
        print(f"Source already exists at {source_dir}")
        return source_dir

    dest_dir.mkdir(parents=True, exist_ok=True)

    print(f"Cloning qwen3-asr-swift ({version})...")
    run_command([
        "git", "clone", "--depth", "1", "--branch", version,
        QWEN3SPEECH_REPO, str(source_dir)
    ])

    return source_dir


def build_swiftpm(source_dir, config):
    """Build qwen3-asr-swift using SwiftPM."""
    print(f"\nBuilding qwen3-asr-swift ({config})...")

    cmd = [
        "swift", "build",
        "-c", config,
        "--disable-sandbox",
    ]

    run_command(cmd, cwd=source_dir)

    # Find the build output directory
    # SwiftPM puts outputs in .build/<triple>/<config>/ or .build/<config>/
    build_dir = source_dir / ".build"

    # Try architecture-specific path first (e.g. .build/arm64-apple-macosx/release/)
    import platform as plat
    arch = plat.machine()  # arm64 on Apple Silicon
    triple_dir = build_dir / f"{arch}-apple-macosx" / config
    if triple_dir.exists():
        return triple_dir

    # Fallback to direct config dir
    config_dir = build_dir / config
    if config_dir.exists():
        return config_dir

    # Search for it
    for d in build_dir.rglob(config):
        if d.is_dir() and (d / "build.db").exists():
            return d

    print(f"Error: Could not find SwiftPM build output under {build_dir}")
    sys.exit(1)


def build_metallib(source_dir, config):
    """Build MLX Metal shader library."""
    script = source_dir / "scripts" / "build_mlx_metallib.sh"
    if not script.exists():
        print(f"Warning: metallib build script not found at {script}")
        print("MLX will use JIT shader compilation (5x slower)")
        return

    print("\nBuilding MLX metallib...")
    run_command(["bash", str(script), config], cwd=source_dir)


def archive_object_files(build_output_dir, lib_dir, module_name):
    """Archive .o files from a SwiftPM module build dir into a static library."""
    module_build_dir = build_output_dir / f"{module_name}.build"
    if not module_build_dir.exists():
        return False

    # Collect all .o files (may be in subdirectories for C modules)
    obj_files = list(module_build_dir.rglob("*.o"))
    # Also include .cc.o files
    obj_files.extend(module_build_dir.rglob("*.cc.o"))

    if not obj_files:
        return False

    lib_name = f"lib{module_name}.a"
    lib_path = lib_dir / lib_name

    # Use ar to create static archive
    cmd = ["ar", "rcs", str(lib_path)] + [str(f) for f in obj_files]
    try:
        subprocess.check_call(cmd)
        print(f"  Archived {len(obj_files)} objects -> {lib_name}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"  Warning: Failed to archive {module_name}: {e}")
        return False


def copy_outputs(source_dir, build_output_dir, output_dir, config):
    """Archive object files into static libs, copy modules and metallib."""

    lib_dir = output_dir / "qwen3speech-mac" / "lib" / "arm64"
    lib_dir.mkdir(parents=True, exist_ok=True)

    # 1. Archive .o files into .a static libraries
    print("\nArchiving static libraries...")
    archived = []
    for module_name in ALL_MODULES_TO_ARCHIVE:
        if archive_object_files(build_output_dir, lib_dir, module_name):
            archived.append(module_name)

    if not archived:
        print(f"Error: No modules could be archived from {build_output_dir}")
        # Debug
        for d in sorted(build_output_dir.iterdir()):
            if d.is_dir() and d.name.endswith(".build"):
                obj_count = len(list(d.rglob("*.o")))
                print(f"  {d.name}: {obj_count} .o files")
        sys.exit(1)

    print(f"\nArchived {len(archived)} libraries: {', '.join(archived)}")

    # 2. Copy Swift module interfaces from Modules/ directory
    modules_dir = build_output_dir / "Modules"
    out_modules_dir = output_dir / "qwen3speech-mac" / "modules"
    out_modules_dir.mkdir(parents=True, exist_ok=True)

    if modules_dir.exists():
        copied_modules = []
        for module_name in WANTED_MODULES + ["MLX", "MLXNN", "MLXFast", "Hub", "Tokenizers"]:
            for ext in [".swiftmodule", ".swiftdoc", ".abi.json", ".swiftsourceinfo"]:
                src = modules_dir / f"{module_name}{ext}"
                if src.exists():
                    dest = out_modules_dir / src.name
                    shutil.copy2(src, dest)
            if (modules_dir / f"{module_name}.swiftmodule").exists():
                copied_modules.append(module_name)

        # Also copy C module maps (e.g. for Cmlx)
        for module_name in ["Cmlx"]:
            include_dir = build_output_dir / f"{module_name}.build" / "include"
            if include_dir.exists():
                dest = out_modules_dir / module_name
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(include_dir, dest)

        print(f"Copied {len(copied_modules)} Swift module interfaces")
    else:
        print(f"Warning: Modules directory not found at {modules_dir}")

    # 3. Copy metallib
    metallib = build_output_dir / "mlx.metallib"
    if not metallib.exists():
        metallib = source_dir / ".build" / config / "mlx.metallib"
    if metallib.exists():
        dest = lib_dir / "mlx.metallib"
        print(f"Copying metallib -> {dest}")
        shutil.copy2(metallib, dest)
    else:
        print("Warning: mlx.metallib not found — MLX will use JIT compilation (slower)")

    # 4. Copy public Swift source files for reference
    include_dir = output_dir / "qwen3speech-mac" / "include"
    include_dir.mkdir(parents=True, exist_ok=True)

    sources_dir = source_dir / "Sources"
    for module_name in WANTED_MODULES:
        module_src = sources_dir / module_name
        if module_src.exists():
            dest_dir = include_dir / module_name
            dest_dir.mkdir(parents=True, exist_ok=True)
            for swift_file in module_src.glob("*.swift"):
                shutil.copy2(swift_file, dest_dir / swift_file.name)

    return lib_dir


def main():
    args = parse_args()

    if args.platform != "mac":
        print("Error: qwen3-asr-swift only supports macOS (requires Apple Silicon + Metal)")
        sys.exit(1)

    if args.archs != "arm64":
        print("Warning: qwen3-asr-swift requires Apple Silicon (arm64). Other architectures are not supported.")

    root_dir = Path(__file__).parent.absolute()
    third_party_dir = root_dir / "third_party"
    build_dir = Path(args.out).absolute()

    # Get source
    if args.local_source:
        source_dir = Path(args.local_source).absolute()
        if not source_dir.exists():
            print(f"Error: Local source not found at {source_dir}")
            sys.exit(1)
        print(f"Using local source at {source_dir}")
    else:
        source_dir = clone_source(args.version, third_party_dir)

    print(f"\n{'='*60}")
    print(f"Building qwen3-asr-swift for {args.platform} {args.archs} ({args.config})")
    print(f"{'='*60}\n")

    # Step 1: Build with SwiftPM
    build_output_dir = build_swiftpm(source_dir, args.config)
    print(f"SwiftPM build output: {build_output_dir}")

    # Step 2: Build MLX metallib
    build_metallib(source_dir, args.config)

    # Step 3: Copy outputs
    copy_outputs(source_dir, build_output_dir, build_dir, args.config)

    print(f"\n{'='*60}")
    print("Build complete!")
    print(f"Output: {build_dir}/qwen3speech-mac/")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
