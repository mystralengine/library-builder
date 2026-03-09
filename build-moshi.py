#!/usr/bin/env python3
"""
Build Moshi (speech-to-speech) and rustymimi (neural audio codec) as static C libraries.

Moshi provides real-time speech-to-speech inference via Rust/Candle.
rustymimi is the Mimi neural audio codec (24kHz audio -> 12.5Hz codes, 80ms latency).

Both are Rust crates compiled as static libraries with C ABI wrappers,
designed to be called from Bun FFI / Electrobun or linked into C++ projects.

Source: https://github.com/kyutai-labs/moshi
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

MOSHI_VERSION = "moshi-v0.2.12"
MOSHI_REPO = "https://github.com/kyutai-labs/moshi.git"


def parse_args():
    parser = argparse.ArgumentParser(description="Build Moshi/rustymimi static C libraries")
    parser.add_argument("platform", choices=["mac", "ios", "android", "linux", "win"],
                        help="Target platform")
    parser.add_argument("-archs", help="Target architecture", default=None)
    parser.add_argument("-config", choices=["release", "debug"], default="release")
    parser.add_argument("-out", help="Output directory", default="build")
    parser.add_argument("-version", help="Moshi version/tag", default=MOSHI_VERSION)
    parser.add_argument("-ndk", help="Android NDK path", default=None)
    return parser.parse_args()


def run_command(cmd, cwd=None, env=None, shell=False):
    print(f"Running: {cmd if shell else ' '.join(cmd)}")
    try:
        subprocess.check_call(cmd, cwd=cwd, env=env, shell=shell)
    except subprocess.CalledProcessError as e:
        print(f"Command failed with exit code {e.returncode}")
        sys.exit(1)


def clone_source(version, dest_dir):
    """Clone Moshi repo at the specified version."""
    # Normalize dir name: "moshi-v0.2.12" -> "moshi-0.2.12", "v0.6.4" -> "moshi-0.6.4"
    clean_version = version.removeprefix("moshi-").removeprefix("v")
    source_dir = dest_dir / f"moshi-{clean_version}"

    if source_dir.exists():
        print(f"Moshi source already exists at {source_dir}")
        return source_dir

    dest_dir.mkdir(parents=True, exist_ok=True)

    print(f"Cloning Moshi {version}...")
    run_command([
        "git", "clone", "--depth", "1", "--branch", version,
        MOSHI_REPO, str(source_dir)
    ])

    return source_dir


def get_default_arch(platform):
    defaults = {
        "mac": "aarch64",
        "ios": "aarch64",
        "android": "aarch64",
        "linux": "x86_64",
        "win": "x86_64",
    }
    return defaults[platform]


def normalize_arch(arch):
    """Normalize arch names to Rust target triples."""
    mapping = {
        "arm64": "aarch64",
        "x64": "x86_64",
        "x86_64": "x86_64",
        "aarch64": "aarch64",
    }
    return mapping.get(arch, arch)


def get_rust_target(platform, arch):
    """Get Rust target triple for platform/arch combo."""
    targets = {
        ("mac", "aarch64"): "aarch64-apple-darwin",
        ("mac", "x86_64"): "x86_64-apple-darwin",
        ("ios", "aarch64"): "aarch64-apple-ios",
        ("linux", "x86_64"): "x86_64-unknown-linux-gnu",
        ("linux", "aarch64"): "aarch64-unknown-linux-gnu",
        ("win", "x86_64"): "x86_64-pc-windows-msvc",
        ("android", "aarch64"): "aarch64-linux-android",
    }
    target = targets.get((platform, arch))
    if not target:
        print(f"Error: Unsupported platform/arch combo: {platform}/{arch}")
        sys.exit(1)
    return target


def get_cargo_features(platform):
    """Get Cargo feature flags for the platform."""
    if platform in ("mac", "ios"):
        return ["metal"]
    elif platform == "linux":
        # CPU-only by default; user can enable CUDA separately
        return []
    elif platform == "win":
        return []
    elif platform == "android":
        return []
    return []


def get_ndk_path(args_ndk):
    if args_ndk:
        return args_ndk
    for env_var in ("ANDROID_NDK_HOME", "ANDROID_NDK_ROOT", "ANDROID_NDK"):
        val = os.environ.get(env_var)
        if val:
            return val
    print("Error: Android NDK not found. Set ANDROID_NDK_HOME or use -ndk flag.")
    sys.exit(1)


def setup_ffi_crate(source_dir):
    """Create the moshi-ffi crate that wraps moshi-core with C ABI exports."""
    ffi_dir = source_dir / "rust" / "moshi-ffi"

    if ffi_dir.exists():
        print(f"moshi-ffi crate already exists at {ffi_dir}")
        return ffi_dir

    ffi_dir.mkdir(parents=True, exist_ok=True)
    src_dir = ffi_dir / "src"
    src_dir.mkdir(exist_ok=True)

    # Write Cargo.toml
    cargo_toml = ffi_dir / "Cargo.toml"
    cargo_toml.write_text("""\
[package]
name = "moshi-ffi"
version = "0.1.0"
edition = "2021"

[lib]
crate-type = ["staticlib", "cdylib"]

[dependencies]
moshi = { path = "../moshi-core" }
candle = { workspace = true }
candle-nn = { workspace = true }
candle-transformers = { workspace = true }

[features]
default = []
cuda = ["moshi/cuda", "candle/cuda", "candle-nn/cuda"]
metal = ["moshi/metal", "candle/metal", "candle-nn/metal"]
""")

    # Write lib.rs with C ABI wrapper functions
    lib_rs = src_dir / "lib.rs"
    lib_rs.write_text("""\
//! C FFI wrapper for Moshi speech-to-speech and Mimi neural audio codec.
//!
//! This crate provides a C-compatible API for:
//! - Loading Moshi models (speech-to-speech LLM)
//! - Encoding/decoding audio with the Mimi codec
//! - Running inference for real-time voice conversation

use std::cell::RefCell;
use std::ffi::{CStr, CString};
use std::os::raw::c_char;

use candle::{DType, Device, Tensor};
use moshi::mimi;
use moshi::lm;

thread_local! {
    static LAST_ERROR: RefCell<Option<CString>> = RefCell::new(None);
}

fn set_error(msg: String) {
    LAST_ERROR.with(|e| {
        *e.borrow_mut() = CString::new(msg).ok();
    });
}

fn clear_error() {
    LAST_ERROR.with(|e| {
        *e.borrow_mut() = None;
    });
}

fn get_device() -> Device {
    #[cfg(feature = "metal")]
    {
        Device::new_metal(0).unwrap_or(Device::Cpu)
    }
    #[cfg(feature = "cuda")]
    {
        Device::new_cuda(0).unwrap_or(Device::Cpu)
    }
    #[cfg(not(any(feature = "metal", feature = "cuda")))]
    {
        Device::Cpu
    }
}

/// Opaque handle to a Mimi codec instance.
pub struct MimiCodec {
    mimi: mimi::Mimi,
    device: Device,
}

/// Opaque handle to a Moshi LM model instance.
pub struct MoshiModel {
    model: lm::LmModel,
    device: Device,
}

/// Initialize the Moshi library. Call once at startup.
/// Returns 0 on success, non-zero on failure.
#[no_mangle]
pub extern "C" fn moshi_init() -> i32 {
    clear_error();
    0
}

/// Load a Mimi codec from a safetensors model file path.
/// num_codebooks: number of codebooks (0 for default = 16).
/// Returns null on failure (call moshi_last_error for details).
#[no_mangle]
pub extern "C" fn mimi_load(
    model_path: *const c_char,
    num_codebooks: u32,
) -> *mut MimiCodec {
    clear_error();
    let path = match unsafe { CStr::from_ptr(model_path) }.to_str() {
        Ok(s) => s,
        Err(_) => {
            set_error("Invalid UTF-8 in model path".into());
            return std::ptr::null_mut();
        }
    };
    let device = get_device();
    let ncb = if num_codebooks == 0 { None } else { Some(num_codebooks as usize) };
    match mimi::load(path, ncb, &device) {
        Ok(mimi) => Box::into_raw(Box::new(MimiCodec { mimi, device })),
        Err(e) => {
            set_error(format!("Failed to load Mimi model: {e}"));
            std::ptr::null_mut()
        }
    }
}

/// Free a Mimi codec instance.
#[no_mangle]
pub extern "C" fn mimi_free(codec: *mut MimiCodec) {
    if !codec.is_null() {
        unsafe { drop(Box::from_raw(codec)) };
    }
}

/// Reset the streaming state of the Mimi codec.
#[no_mangle]
pub extern "C" fn mimi_reset(codec: *mut MimiCodec) {
    if codec.is_null() { return; }
    let codec = unsafe { &mut *codec };
    codec.mimi.reset_state();
}

/// Encode PCM audio (f32, 24kHz, mono) into Mimi audio codes.
/// pcm_data: pointer to float32 PCM samples.
/// pcm_len: number of samples.
/// codes_out: output buffer for u32 codes (layout: num_codebooks * num_frames).
/// codes_capacity: capacity of codes_out buffer in u32 elements.
/// out_num_codebooks: receives the number of codebooks written.
/// Returns the number of frames written (codes_out has num_codebooks * frames elements),
/// or -1 on error.
#[no_mangle]
pub extern "C" fn mimi_encode(
    codec: *mut MimiCodec,
    pcm_data: *const f32,
    pcm_len: usize,
    codes_out: *mut u32,
    codes_capacity: usize,
    out_num_codebooks: *mut u32,
) -> i32 {
    clear_error();
    if codec.is_null() || pcm_data.is_null() || codes_out.is_null() {
        set_error("Null pointer argument".into());
        return -1;
    }
    let codec = unsafe { &mut *codec };
    let pcm_slice = unsafe { std::slice::from_raw_parts(pcm_data, pcm_len) };

    let result = (|| -> Result<i32, String> {
        // Shape: [batch=1, channels=1, samples]
        let pcm_tensor = Tensor::from_slice(pcm_slice, (1, 1, pcm_len), &codec.device)
            .map_err(|e| format!("Failed to create PCM tensor: {e}"))?;
        // Returns shape [batch=1, num_codebooks, num_frames]
        let codes = codec.mimi.encode(&pcm_tensor)
            .map_err(|e| format!("Encode failed: {e}"))?;
        let codes_vec = codes.to_vec3::<u32>()
            .map_err(|e| format!("Failed to extract codes: {e}"))?;

        if codes_vec.is_empty() || codes_vec[0].is_empty() {
            return Ok(0);
        }
        let num_codebooks = codes_vec[0].len();
        let num_frames = codes_vec[0][0].len();
        let total = num_codebooks * num_frames;

        if total > codes_capacity {
            return Err(format!(
                "Output buffer too small: need {total}, have {codes_capacity}"
            ));
        }

        let out_slice = unsafe { std::slice::from_raw_parts_mut(codes_out, total) };
        for (cb_idx, cb) in codes_vec[0].iter().enumerate() {
            for (frame_idx, &code) in cb.iter().enumerate() {
                out_slice[cb_idx * num_frames + frame_idx] = code;
            }
        }

        if !out_num_codebooks.is_null() {
            unsafe { *out_num_codebooks = num_codebooks as u32 };
        }

        Ok(num_frames as i32)
    })();

    match result {
        Ok(n) => n,
        Err(e) => { set_error(e); -1 }
    }
}

/// Encode a single step for streaming (encode_step).
/// pcm_data: pointer to float32 PCM samples for one frame (1920 samples at 24kHz = 80ms).
/// pcm_len: number of samples.
/// codes_out: output buffer for u32 codes (num_codebooks elements).
/// codes_capacity: capacity of codes_out buffer.
/// Returns number of codebooks written, 0 if no output yet (buffering), or -1 on error.
#[no_mangle]
pub extern "C" fn mimi_encode_step(
    codec: *mut MimiCodec,
    pcm_data: *const f32,
    pcm_len: usize,
    codes_out: *mut u32,
    codes_capacity: usize,
) -> i32 {
    clear_error();
    if codec.is_null() || pcm_data.is_null() || codes_out.is_null() {
        set_error("Null pointer argument".into());
        return -1;
    }
    let codec = unsafe { &mut *codec };
    let pcm_slice = unsafe { std::slice::from_raw_parts(pcm_data, pcm_len) };

    let result = (|| -> Result<i32, String> {
        let pcm_tensor = Tensor::from_slice(pcm_slice, (1, 1, pcm_len), &codec.device)
            .map_err(|e| format!("Failed to create tensor: {e}"))?;
        let stream_tensor: moshi::StreamTensor = pcm_tensor.into();
        let codes = codec.mimi.encode_step(&stream_tensor, &().into())
            .map_err(|e| format!("Encode step failed: {e}"))?;

        match codes.as_option() {
            None => Ok(0), // still buffering
            Some(codes_t) => {
                // Shape: [1, num_codebooks, 1]
                let codes_vec = codes_t.to_vec3::<u32>()
                    .map_err(|e| format!("Failed to extract codes: {e}"))?;
                if codes_vec.is_empty() || codes_vec[0].is_empty() {
                    return Ok(0);
                }
                let num_codebooks = codes_vec[0].len();
                if num_codebooks > codes_capacity {
                    return Err(format!(
                        "Output buffer too small: need {num_codebooks}, have {codes_capacity}"
                    ));
                }
                let out_slice = unsafe {
                    std::slice::from_raw_parts_mut(codes_out, num_codebooks)
                };
                for (i, cb) in codes_vec[0].iter().enumerate() {
                    out_slice[i] = cb[0];
                }
                Ok(num_codebooks as i32)
            }
        }
    })();

    match result {
        Ok(n) => n,
        Err(e) => { set_error(e); -1 }
    }
}

/// Decode Mimi audio codes back to PCM audio (f32, 24kHz, mono).
/// codes: pointer to u32 codes (layout: num_codebooks * num_frames).
/// num_codebooks: number of codebooks.
/// num_frames: number of frames.
/// pcm_out: output buffer for f32 PCM samples.
/// pcm_capacity: capacity of pcm_out buffer.
/// Returns the number of PCM samples written, or -1 on error.
#[no_mangle]
pub extern "C" fn mimi_decode(
    codec: *mut MimiCodec,
    codes: *const u32,
    num_codebooks: usize,
    num_frames: usize,
    pcm_out: *mut f32,
    pcm_capacity: usize,
) -> i32 {
    clear_error();
    if codec.is_null() || codes.is_null() || pcm_out.is_null() {
        set_error("Null pointer argument".into());
        return -1;
    }
    let codec = unsafe { &mut *codec };
    let total_codes = num_codebooks * num_frames;
    let codes_slice = unsafe { std::slice::from_raw_parts(codes, total_codes) };

    let result = (|| -> Result<i32, String> {
        // Build [1, num_codebooks, num_frames] tensor
        let mut codes_vec = vec![0u32; total_codes];
        codes_vec.copy_from_slice(codes_slice);
        let codes_tensor = Tensor::from_vec(
            codes_vec, (1, num_codebooks, num_frames), &codec.device
        ).map_err(|e| format!("Failed to create codes tensor: {e}"))?;

        let pcm = codec.mimi.decode(&codes_tensor)
            .map_err(|e| format!("Decode failed: {e}"))?;
        let pcm = pcm.to_dtype(DType::F32)
            .map_err(|e| format!("dtype conversion failed: {e}"))?;
        // Shape: [1, 1, num_samples]
        let pcm_vec = pcm.to_vec3::<f32>()
            .map_err(|e| format!("Failed to extract PCM: {e}"))?;

        if pcm_vec.is_empty() || pcm_vec[0].is_empty() {
            return Ok(0);
        }
        let samples = &pcm_vec[0][0];
        if samples.len() > pcm_capacity {
            return Err(format!(
                "PCM output buffer too small: need {}, have {pcm_capacity}",
                samples.len()
            ));
        }
        let out_slice = unsafe { std::slice::from_raw_parts_mut(pcm_out, samples.len()) };
        out_slice.copy_from_slice(samples);
        Ok(samples.len() as i32)
    })();

    match result {
        Ok(n) => n,
        Err(e) => { set_error(e); -1 }
    }
}

/// Decode a single step for streaming (decode_step).
/// codes: pointer to u32 codes for one frame (num_codebooks elements).
/// num_codebooks: number of codebooks.
/// pcm_out: output buffer for f32 PCM samples.
/// pcm_capacity: capacity of pcm_out buffer.
/// Returns number of PCM samples written, 0 if no output yet, or -1 on error.
#[no_mangle]
pub extern "C" fn mimi_decode_step(
    codec: *mut MimiCodec,
    codes: *const u32,
    num_codebooks: usize,
    pcm_out: *mut f32,
    pcm_capacity: usize,
) -> i32 {
    clear_error();
    if codec.is_null() || codes.is_null() || pcm_out.is_null() {
        set_error("Null pointer argument".into());
        return -1;
    }
    let codec = unsafe { &mut *codec };
    let codes_slice = unsafe { std::slice::from_raw_parts(codes, num_codebooks) };

    let result = (|| -> Result<i32, String> {
        // Build codes tensor with shape [1, num_codebooks, 1] (batch, codebooks, frames)
        let codes_vec: Vec<u32> = codes_slice.to_vec();
        let codes_tensor = Tensor::from_vec(
            codes_vec, (1, num_codebooks, 1), &codec.device
        ).map_err(|e| format!("Failed to create codes tensor: {e}"))?;
        let stream_tensor: moshi::StreamTensor = codes_tensor.into();
        let pcm = codec.mimi.decode_step(&stream_tensor, &().into())
            .map_err(|e| format!("Decode step failed: {e}"))?;

        match pcm.as_option() {
            None => Ok(0),
            Some(pcm_t) => {
                let pcm_t = pcm_t.to_dtype(DType::F32)
                    .map_err(|e| format!("dtype conversion failed: {e}"))?;
                let pcm_vec = pcm_t.to_vec3::<f32>()
                    .map_err(|e| format!("Failed to extract PCM: {e}"))?;
                if pcm_vec.is_empty() || pcm_vec[0].is_empty() {
                    return Ok(0);
                }
                let samples = &pcm_vec[0][0];
                if samples.len() > pcm_capacity {
                    return Err(format!(
                        "PCM output buffer too small: need {}, have {pcm_capacity}",
                        samples.len()
                    ));
                }
                let out_slice = unsafe {
                    std::slice::from_raw_parts_mut(pcm_out, samples.len())
                };
                out_slice.copy_from_slice(samples);
                Ok(samples.len() as i32)
            }
        }
    })();

    match result {
        Ok(n) => n,
        Err(e) => { set_error(e); -1 }
    }
}

/// Load a Moshi speech-to-speech model from a safetensors or gguf file.
/// Returns null on failure.
#[no_mangle]
pub extern "C" fn moshi_load(model_path: *const c_char) -> *mut MoshiModel {
    clear_error();
    let path = match unsafe { CStr::from_ptr(model_path) }.to_str() {
        Ok(s) => s,
        Err(_) => {
            set_error("Invalid UTF-8 in model path".into());
            return std::ptr::null_mut();
        }
    };
    let device = get_device();
    match lm::load(path, DType::F32, &device) {
        Ok(model) => Box::into_raw(Box::new(MoshiModel { model, device })),
        Err(e) => {
            set_error(format!("Failed to load Moshi model: {e}"));
            std::ptr::null_mut()
        }
    }
}

/// Free a Moshi model instance.
#[no_mangle]
pub extern "C" fn moshi_free(model: *mut MoshiModel) {
    if !model.is_null() {
        unsafe { drop(Box::from_raw(model)) };
    }
}

/// Reset the Moshi model's internal state (KV cache).
#[no_mangle]
pub extern "C" fn moshi_reset(model: *mut MoshiModel) {
    if model.is_null() { return; }
    let model = unsafe { &mut *model };
    model.model.reset_state();
}

/// Get the number of input audio codebooks expected by the model.
#[no_mangle]
pub extern "C" fn moshi_audio_codebooks(model: *const MoshiModel) -> u32 {
    if model.is_null() { return 0; }
    let model = unsafe { &*model };
    model.model.in_audio_codebooks() as u32
}

/// Get the audio pad token value.
#[no_mangle]
pub extern "C" fn moshi_audio_pad_token(model: *const MoshiModel) -> u32 {
    if model.is_null() { return 0; }
    let model = unsafe { &*model };
    model.model.audio_pad_token()
}

/// Get the text start token value.
#[no_mangle]
pub extern "C" fn moshi_text_start_token(model: *const MoshiModel) -> u32 {
    if model.is_null() { return 0; }
    let model = unsafe { &*model };
    model.model.text_start_token()
}

/// Run one forward pass of the Moshi LM.
/// text_token: input text token (use moshi_text_start_token() for initial).
/// audio_codes: input audio codes (num_codebooks elements).
/// num_codebooks: number of audio codebooks.
/// text_logits_out: output buffer for text logits.
/// text_logits_capacity: capacity of text_logits_out.
/// out_text_logits_len: receives actual number of text logits written.
/// Returns 0 on success, -1 on error.
#[no_mangle]
pub extern "C" fn moshi_forward(
    model: *mut MoshiModel,
    text_token: u32,
    audio_codes: *const u32,
    num_codebooks: usize,
    text_logits_out: *mut f32,
    text_logits_capacity: usize,
    out_text_logits_len: *mut u32,
) -> i32 {
    clear_error();
    if model.is_null() || audio_codes.is_null() || text_logits_out.is_null() {
        set_error("Null pointer argument".into());
        return -1;
    }
    let model = unsafe { &mut *model };
    let audio_slice = unsafe { std::slice::from_raw_parts(audio_codes, num_codebooks) };

    let result = (|| -> Result<(), String> {
        let text_ids = Tensor::from_vec(
            vec![text_token], (1, 1), &model.device
        ).map_err(|e| format!("text tensor: {e}"))?;

        let audio_ids: Vec<Option<Tensor>> = audio_slice.iter().map(|&code| {
            Tensor::from_vec(vec![code], (1, 1), &model.device).ok()
        }).collect();

        let mask: moshi::StreamMask = ().into();
        let (text_logits, _audio_logits) = model.model.forward(
            Some(text_ids), audio_ids, &mask
        ).map_err(|e| format!("Forward failed: {e}"))?;

        // text_logits shape: [1, 1, vocab_size] -> flatten
        let logits_vec = text_logits.to_vec3::<f32>()
            .map_err(|e| format!("Failed to extract logits: {e}"))?;
        if logits_vec.is_empty() || logits_vec[0].is_empty() {
            if !out_text_logits_len.is_null() {
                unsafe { *out_text_logits_len = 0 };
            }
            return Ok(());
        }
        let logits = &logits_vec[0][0];
        if logits.len() > text_logits_capacity {
            return Err(format!(
                "Text logits buffer too small: need {}, have {text_logits_capacity}",
                logits.len()
            ));
        }
        let out_slice = unsafe {
            std::slice::from_raw_parts_mut(text_logits_out, logits.len())
        };
        out_slice.copy_from_slice(logits);
        if !out_text_logits_len.is_null() {
            unsafe { *out_text_logits_len = logits.len() as u32 };
        }
        Ok(())
    })();

    match result {
        Ok(()) => 0,
        Err(e) => { set_error(e); -1 }
    }
}

/// Get the last error message. Returns null if no error.
/// The returned string is valid until the next FFI call.
#[no_mangle]
pub extern "C" fn moshi_last_error() -> *const c_char {
    LAST_ERROR.with(|e| {
        match e.borrow().as_ref() {
            Some(s) => s.as_ptr(),
            None => std::ptr::null(),
        }
    })
}
""")

    # Add moshi-ffi to workspace members
    workspace_toml = source_dir / "rust" / "Cargo.toml"
    content = workspace_toml.read_text()
    if "moshi-ffi" not in content:
        content = content.replace(
            '"moshi-core"',
            '"moshi-core",\n    "moshi-ffi"'
        )
        workspace_toml.write_text(content)

    print(f"Created moshi-ffi crate at {ffi_dir}")
    return ffi_dir


def write_c_header(output_dir):
    """Write the C header file for the FFI interface."""
    include_dir = output_dir / "include" / "moshi"
    include_dir.mkdir(parents=True, exist_ok=True)

    header = include_dir / "moshi.h"
    header.write_text("""\
#ifndef MOSHI_FFI_H
#define MOSHI_FFI_H

#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Opaque handles */
typedef struct MimiCodec MimiCodec;
typedef struct MoshiModel MoshiModel;

/* Library initialization */
int32_t moshi_init(void);

/* Mimi codec (neural audio codec, 24kHz mono, 12.5Hz frame rate) */
MimiCodec* mimi_load(const char* model_path, uint32_t num_codebooks);
void mimi_free(MimiCodec* codec);
void mimi_reset(MimiCodec* codec);

/* Batch encode/decode (non-streaming) */
int32_t mimi_encode(MimiCodec* codec, const float* pcm_data, size_t pcm_len,
                    uint32_t* codes_out, size_t codes_capacity,
                    uint32_t* out_num_codebooks);
int32_t mimi_decode(MimiCodec* codec, const uint32_t* codes,
                    size_t num_codebooks, size_t num_frames,
                    float* pcm_out, size_t pcm_capacity);

/* Streaming encode/decode (one frame at a time) */
int32_t mimi_encode_step(MimiCodec* codec, const float* pcm_data, size_t pcm_len,
                         uint32_t* codes_out, size_t codes_capacity);
int32_t mimi_decode_step(MimiCodec* codec, const uint32_t* codes,
                         size_t num_codebooks,
                         float* pcm_out, size_t pcm_capacity);

/* Moshi model (speech-to-speech LLM) */
MoshiModel* moshi_load(const char* model_path);
void moshi_free(MoshiModel* model);
void moshi_reset(MoshiModel* model);

/* Model properties */
uint32_t moshi_audio_codebooks(const MoshiModel* model);
uint32_t moshi_audio_pad_token(const MoshiModel* model);
uint32_t moshi_text_start_token(const MoshiModel* model);

/* Forward pass - returns text logits */
int32_t moshi_forward(MoshiModel* model,
                      uint32_t text_token,
                      const uint32_t* audio_codes, size_t num_codebooks,
                      float* text_logits_out, size_t text_logits_capacity,
                      uint32_t* out_text_logits_len);

/* Error handling */
const char* moshi_last_error(void);

#ifdef __cplusplus
}
#endif

#endif /* MOSHI_FFI_H */
""")

    print(f"Wrote C header to {header}")


def build_moshi(source_dir, output_dir, platform, arch, config, ndk_path=None):
    """Build moshi-ffi using Cargo."""
    rust_dir = source_dir / "rust"
    target = get_rust_target(platform, arch)
    features = get_cargo_features(platform)

    # Ensure Cargo/Rustup are in PATH (e.g. when installed via rustup)
    cargo_bin = Path.home() / ".cargo" / "bin"
    if cargo_bin.exists():
        os.environ["PATH"] = f"{cargo_bin}:{os.environ.get('PATH', '')}"

    # Ensure the target is installed
    run_command(["rustup", "target", "add", target])

    # Build command
    cmd = ["cargo", "build", "--package", "moshi-ffi", "--target", target]

    if config == "release":
        cmd.append("--release")

    if features:
        cmd.extend(["--features", ",".join(features)])

    # Set up environment for cross-compilation
    env = os.environ.copy()

    if platform == "android":
        ndk = get_ndk_path(ndk_path)
        # Android NDK toolchain
        toolchain_bin = os.path.join(ndk, "toolchains", "llvm", "prebuilt",
                                     f"{'darwin' if sys.platform == 'darwin' else 'linux'}-x86_64", "bin")
        env["CC_aarch64-linux-android"] = os.path.join(toolchain_bin, "aarch64-linux-android28-clang")
        env["CXX_aarch64-linux-android"] = os.path.join(toolchain_bin, "aarch64-linux-android28-clang++")
        env["AR_aarch64-linux-android"] = os.path.join(toolchain_bin, "llvm-ar")
        env["CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER"] = env["CC_aarch64-linux-android"]

    run_command(cmd, cwd=rust_dir, env=env)

    # Copy output
    profile = "release" if config == "release" else "debug"
    lib_dir = rust_dir / "target" / target / profile

    out_lib_dir = output_dir / f"moshi-{platform}" / "lib"
    if platform in ("mac", "ios"):
        out_lib_dir = out_lib_dir / arch
    out_lib_dir.mkdir(parents=True, exist_ok=True)

    # Find and copy the static library
    if platform == "win":
        static_name = "moshi_ffi.lib"
    else:
        static_name = "libmoshi_ffi.a"

    static_path = lib_dir / static_name
    if static_path.exists():
        dest = out_lib_dir / static_name
        print(f"Copying {static_path} -> {dest}")
        shutil.copy2(static_path, dest)
    else:
        print(f"Error: Static library not found at {static_path}")
        # List what's there for debugging
        for f in lib_dir.glob("*moshi*"):
            print(f"  Found: {f}")
        sys.exit(1)

    # Also copy the shared library (for Bun FFI / dlopen)
    if platform in ("mac", "ios"):
        shared_name = "libmoshi_ffi.dylib"
    elif platform == "win":
        shared_name = "moshi_ffi.dll"
    else:
        shared_name = "libmoshi_ffi.so"

    shared_path = lib_dir / shared_name
    if shared_path.exists():
        dest = out_lib_dir / shared_name
        print(f"Copying {shared_path} -> {dest}")
        shutil.copy2(shared_path, dest)
    else:
        print(f"Warning: Shared library not found at {shared_path} (OK for static-only builds)")

    return out_lib_dir


def main():
    args = parse_args()

    root_dir = Path(__file__).parent.absolute()
    third_party_dir = root_dir / "third_party"
    build_dir = Path(args.out).absolute()

    # Clone source
    source_dir = clone_source(args.version, third_party_dir)

    # Set up the FFI wrapper crate
    setup_ffi_crate(source_dir)

    arch = normalize_arch(args.archs or get_default_arch(args.platform))

    print(f"\n{'='*60}")
    print(f"Building Moshi FFI for {args.platform} {arch} ({args.config})")
    print(f"{'='*60}\n")

    build_moshi(
        source_dir, build_dir, args.platform, arch, args.config,
        ndk_path=args.ndk,
    )

    # Write C header
    write_c_header(build_dir)

    print(f"\n{'='*60}")
    print("Build complete!")
    print(f"Output: {build_dir}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
