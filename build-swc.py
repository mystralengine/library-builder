#!/usr/bin/env python3

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

def parse_args():
    parser = argparse.ArgumentParser(description="Build SWC static library")
    parser.add_argument("platform", choices=["mac", "linux", "win"], help="Target platform")
    parser.add_argument("-archs", help="Target architectures (comma separated)", default="x64")
    parser.add_argument("-config", choices=["Release", "Debug"], default="Release")
    parser.add_argument("-out", help="Output directory", default="build")
    return parser.parse_args()

def get_rust_target(platform, arch):
    if platform == "mac":
        if arch == "arm64":
            return "aarch64-apple-darwin"
        elif arch == "x64" or arch == "x86_64":
            return "x86_64-apple-darwin"
    elif platform == "linux":
        if arch == "x64" or arch == "x86_64":
            return "x86_64-unknown-linux-gnu"
    elif platform == "win":
        if arch == "x64" or arch == "x86_64":
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

def main():
    args = parse_args()
    
    root_dir = Path(__file__).parent.absolute()
    swc_dir = root_dir / "third_party" / "swc-static"
    build_dir = Path(args.out)
    
    # Ensure rustup/cargo is available
    try:
        subprocess.check_call(["cargo", "--version"], stdout=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Error: 'cargo' not found. Please install Rust.")
        sys.exit(1)

    archs = args.archs.split(",")
    
    for arch in archs:
        arch = arch.strip()
        target = get_rust_target(args.platform, arch)
        
        print(f"Building for {args.platform} {arch} ({target})...")
        
        # Add target if not installed
        run_command(["rustup", "target", "add", target])
        
        cargo_cmd = ["cargo", "build", "--target", target]
        if args.config == "Release":
            cargo_cmd.append("--release")
            
        run_command(cargo_cmd, cwd=swc_dir)
        
        # Determine output artifact path
        profile = "release" if args.config == "Release" else "debug"
        lib_name = "libswc_static.a"
        if args.platform == "win":
            lib_name = "swc_static.lib"
            
        src_lib = swc_dir / "target" / target / profile / lib_name
        
        # Prepare destination
        dest_dir = build_dir / f"swc-{args.platform}" / "lib"
        if args.platform == "mac" and len(archs) > 1:
             dest_dir = build_dir / f"swc-{args.platform}" / "lib" / arch
             
        dest_dir.mkdir(parents=True, exist_ok=True)
        
        dest_lib = dest_dir / ("libswc.a" if args.platform != "win" else "swc.lib")
        
        print(f"Copying {src_lib} to {dest_lib}")
        shutil.copy2(src_lib, dest_lib)

    # Copy header
    header_src = swc_dir / "include" / "swc.h"
    header_dest = build_dir / "include" / "swc.h"
    header_dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(header_src, header_dest)
    
    print("Build complete.")

if __name__ == "__main__":
    main()
