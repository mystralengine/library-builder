/**
 * End-to-end test for libmoshi_ffi: Mimi encode/decode + Moshi LM forward pass.
 *
 * Pipeline: Generate PCM sine wave -> mimi_encode -> moshi_forward -> mimi_decode -> WAV file
 *
 * Build (Linux):
 *   gcc -o test_moshi test_moshi.c \
 *       -L../build/moshi-linux/lib -lmoshi_ffi \
 *       -lm -lpthread -ldl -lstdc++
 *
 * Build (macOS arm64):
 *   clang -o test_moshi test_moshi.c \
 *       -L../build/moshi-mac/lib/aarch64 -lmoshi_ffi \
 *       -framework Accelerate -framework Metal -framework MetalPerformanceShaders \
 *       -lc++ -lm -lpthread
 *
 * Usage:
 *   ./test_moshi <mimi_model_path> <moshi_model_path> [output.wav]
 *
 * Example:
 *   ./test_moshi ~/.pixieai/models/mimi/model.safetensors \
 *                ~/.pixieai/models/moshiko/model.safetensors \
 *                output.wav
 *
 * References:
 *   - Defossez et al., "Moshi: a speech-text foundation model for real-time dialogue" (2024)
 *   - Mimi codec: 24kHz mono, 12.5Hz frame rate, 1920 samples/frame (80ms latency)
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <stdint.h>

/* Include the FFI header */
#include "../build/include/moshi/moshi.h"

/* WAV header constants */
#define WAV_SAMPLE_RATE 24000
#define WAV_CHANNELS 1
#define WAV_BITS_PER_SAMPLE 16

/* Mimi frame size: 1920 samples at 24kHz = 80ms */
#define MIMI_FRAME_SAMPLES 1920

/* Test signal: 1 second of 440Hz sine wave at 24kHz */
#define TEST_DURATION_SEC 1.0f
#define TEST_FREQUENCY_HZ 440.0f
#define TEST_NUM_SAMPLES ((int)(WAV_SAMPLE_RATE * TEST_DURATION_SEC))

/* Maximum buffers */
#define MAX_CODEBOOKS 32
#define MAX_FRAMES 256
#define MAX_PCM_OUT (MIMI_FRAME_SAMPLES * MAX_FRAMES)
#define MAX_TEXT_VOCAB 65536

static const char* check_error(void) {
    const char* err = moshi_last_error();
    return err ? err : "unknown error";
}

/**
 * Generate a test PCM signal: 440Hz sine wave, 24kHz, mono, float32.
 */
static float* generate_test_pcm(int num_samples) {
    float* pcm = (float*)malloc(num_samples * sizeof(float));
    if (!pcm) return NULL;

    for (int i = 0; i < num_samples; i++) {
        /* A4 sine wave, amplitude 0.5 to avoid clipping */
        pcm[i] = 0.5f * sinf(2.0f * (float)M_PI * TEST_FREQUENCY_HZ * (float)i / (float)WAV_SAMPLE_RATE);
    }
    return pcm;
}

/**
 * Write PCM float32 data to a 16-bit WAV file.
 */
static int write_wav(const char* path, const float* pcm, int num_samples) {
    FILE* f = fopen(path, "wb");
    if (!f) {
        fprintf(stderr, "Error: cannot open %s for writing\n", path);
        return -1;
    }

    int data_size = num_samples * WAV_CHANNELS * (WAV_BITS_PER_SAMPLE / 8);
    int file_size = 36 + data_size;

    /* RIFF header */
    fwrite("RIFF", 1, 4, f);
    uint32_t chunk_size = (uint32_t)file_size;
    fwrite(&chunk_size, 4, 1, f);
    fwrite("WAVE", 1, 4, f);

    /* fmt sub-chunk */
    fwrite("fmt ", 1, 4, f);
    uint32_t fmt_size = 16;
    fwrite(&fmt_size, 4, 1, f);
    uint16_t audio_format = 1; /* PCM */
    fwrite(&audio_format, 2, 1, f);
    uint16_t channels = WAV_CHANNELS;
    fwrite(&channels, 2, 1, f);
    uint32_t sample_rate = WAV_SAMPLE_RATE;
    fwrite(&sample_rate, 4, 1, f);
    uint32_t byte_rate = WAV_SAMPLE_RATE * WAV_CHANNELS * (WAV_BITS_PER_SAMPLE / 8);
    fwrite(&byte_rate, 4, 1, f);
    uint16_t block_align = WAV_CHANNELS * (WAV_BITS_PER_SAMPLE / 8);
    fwrite(&block_align, 2, 1, f);
    uint16_t bits_per_sample = WAV_BITS_PER_SAMPLE;
    fwrite(&bits_per_sample, 2, 1, f);

    /* data sub-chunk */
    fwrite("data", 1, 4, f);
    uint32_t data_chunk_size = (uint32_t)data_size;
    fwrite(&data_chunk_size, 4, 1, f);

    /* Convert float32 [-1,1] to int16 */
    for (int i = 0; i < num_samples; i++) {
        float s = pcm[i];
        if (s > 1.0f) s = 1.0f;
        if (s < -1.0f) s = -1.0f;
        int16_t sample = (int16_t)(s * 32767.0f);
        fwrite(&sample, 2, 1, f);
    }

    fclose(f);
    printf("  Wrote %d samples (%.2fs) to %s\n", num_samples,
           (float)num_samples / WAV_SAMPLE_RATE, path);
    return 0;
}

int main(int argc, char** argv) {
    if (argc < 3) {
        fprintf(stderr, "Usage: %s <mimi_model_path> <moshi_model_path> [output.wav]\n", argv[0]);
        fprintf(stderr, "\nExample:\n");
        fprintf(stderr, "  %s ~/.pixieai/models/mimi/model.safetensors \\\n", argv[0]);
        fprintf(stderr, "     ~/.pixieai/models/moshiko/model.safetensors \\\n");
        fprintf(stderr, "     output.wav\n");
        return 1;
    }

    const char* mimi_path = argv[1];
    const char* moshi_path = argv[2];
    const char* output_path = argc > 3 ? argv[3] : "test_output.wav";

    printf("=== Moshi FFI End-to-End Test ===\n\n");

    /* Step 1: Initialize library */
    printf("[1/7] Initializing Moshi library...\n");
    int rc = moshi_init();
    if (rc != 0) {
        fprintf(stderr, "  FAIL: moshi_init returned %d: %s\n", rc, check_error());
        return 1;
    }
    printf("  OK\n");

    /* Step 2: Load Mimi codec */
    printf("[2/7] Loading Mimi codec from: %s\n", mimi_path);
    MimiCodec* codec = mimi_load(mimi_path, 0); /* 0 = default codebooks */
    if (!codec) {
        fprintf(stderr, "  FAIL: %s\n", check_error());
        return 1;
    }
    printf("  OK\n");

    /* Step 3: Load Moshi model */
    printf("[3/7] Loading Moshi model from: %s\n", moshi_path);
    MoshiModel* model = moshi_load(moshi_path);
    if (!model) {
        fprintf(stderr, "  FAIL: %s\n", check_error());
        mimi_free(codec);
        return 1;
    }

    uint32_t num_codebooks = moshi_audio_codebooks(model);
    uint32_t pad_token = moshi_audio_pad_token(model);
    uint32_t text_start = moshi_text_start_token(model);
    printf("  OK (codebooks=%u, pad_token=%u, text_start=%u)\n",
           num_codebooks, pad_token, text_start);

    /* Step 4: Generate test PCM (440Hz sine) */
    printf("[4/7] Generating test PCM (%.0fHz sine, %.1fs, %d samples)...\n",
           TEST_FREQUENCY_HZ, TEST_DURATION_SEC, TEST_NUM_SAMPLES);
    float* input_pcm = generate_test_pcm(TEST_NUM_SAMPLES);
    if (!input_pcm) {
        fprintf(stderr, "  FAIL: malloc\n");
        moshi_free(model);
        mimi_free(codec);
        return 1;
    }
    printf("  OK\n");

    /* Step 5: Encode PCM -> audio codes via Mimi */
    printf("[5/7] Encoding PCM to Mimi audio codes...\n");
    uint32_t codes_buf[MAX_CODEBOOKS * MAX_FRAMES];
    uint32_t out_num_codebooks = 0;

    int32_t num_frames = mimi_encode(
        codec, input_pcm, TEST_NUM_SAMPLES,
        codes_buf, MAX_CODEBOOKS * MAX_FRAMES,
        &out_num_codebooks
    );

    if (num_frames < 0) {
        fprintf(stderr, "  FAIL: mimi_encode: %s\n", check_error());
        free(input_pcm);
        moshi_free(model);
        mimi_free(codec);
        return 1;
    }
    printf("  OK: %d frames, %u codebooks\n", num_frames, out_num_codebooks);

    /* Step 6: Run Moshi forward pass for each frame */
    printf("[6/7] Running Moshi forward pass (%d steps)...\n", num_frames);
    float logits_buf[MAX_TEXT_VOCAB];
    uint32_t logits_len = 0;
    uint32_t text_token = text_start;
    int forward_errors = 0;

    /* We'll use the encoded codes as both input and response codes for decode.
     * In a real deployment, the model's depformer would generate response audio
     * codes, but for this test we validate the encode->forward->decode roundtrip. */
    for (int frame = 0; frame < num_frames && frame < 10; frame++) {
        /* Extract audio codes for this frame */
        uint32_t frame_codes[MAX_CODEBOOKS];
        for (uint32_t cb = 0; cb < out_num_codebooks; cb++) {
            frame_codes[cb] = codes_buf[cb * num_frames + frame];
        }

        rc = moshi_forward(
            model, text_token,
            frame_codes, num_codebooks,
            logits_buf, MAX_TEXT_VOCAB,
            &logits_len
        );

        if (rc != 0) {
            fprintf(stderr, "  FAIL at frame %d: %s\n", frame, check_error());
            forward_errors++;
            break;
        }

        /* Greedy decode: pick argmax text token */
        if (logits_len > 0) {
            float max_val = logits_buf[0];
            uint32_t max_idx = 0;
            for (uint32_t i = 1; i < logits_len; i++) {
                if (logits_buf[i] > max_val) {
                    max_val = logits_buf[i];
                    max_idx = i;
                }
            }
            text_token = max_idx;
        }

        if (frame < 3 || frame == num_frames - 1) {
            printf("  Frame %d: logits_len=%u, text_token=%u\n",
                   frame, logits_len, text_token);
        } else if (frame == 3) {
            printf("  ...\n");
        }
    }

    if (forward_errors > 0) {
        printf("  Forward pass had %d errors\n", forward_errors);
    } else {
        printf("  OK: forward pass completed for %d frames\n",
               num_frames < 10 ? num_frames : 10);
    }

    /* Step 7: Decode audio codes back to PCM via Mimi */
    printf("[7/7] Decoding audio codes back to PCM...\n");

    /* Reset Mimi state before decode (encoder state shouldn't bleed into decoder) */
    mimi_reset(codec);

    float pcm_out[MAX_PCM_OUT];
    int32_t num_samples_out = mimi_decode(
        codec, codes_buf,
        out_num_codebooks, num_frames,
        pcm_out, MAX_PCM_OUT
    );

    if (num_samples_out < 0) {
        fprintf(stderr, "  FAIL: mimi_decode: %s\n", check_error());
        free(input_pcm);
        moshi_free(model);
        mimi_free(codec);
        return 1;
    }
    printf("  OK: decoded %d PCM samples (%.2fs)\n",
           num_samples_out, (float)num_samples_out / WAV_SAMPLE_RATE);

    /* Write output WAV */
    if (num_samples_out > 0) {
        write_wav(output_path, pcm_out, num_samples_out);
    }

    /* Also write input WAV for comparison */
    {
        char input_wav[256];
        snprintf(input_wav, sizeof(input_wav), "test_input.wav");
        write_wav(input_wav, input_pcm, TEST_NUM_SAMPLES);
    }

    /* Cleanup */
    free(input_pcm);
    moshi_free(model);
    mimi_free(codec);

    printf("\n=== Test Complete ===\n");
    printf("Input:  test_input.wav (%d samples, %.2fs)\n",
           TEST_NUM_SAMPLES, TEST_DURATION_SEC);
    printf("Output: %s (%d samples, %.2fs)\n",
           output_path, num_samples_out,
           num_samples_out > 0 ? (float)num_samples_out / WAV_SAMPLE_RATE : 0.0f);

    return forward_errors > 0 ? 1 : 0;
}
