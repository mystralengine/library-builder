# Makefile for building and running moshi-ffi tests
#
# Usage:
#   make test_moshi           # Build the test
#   make run                  # Build and run (requires model paths)
#   make clean                # Clean build artifacts

UNAME_S := $(shell uname -s)
UNAME_M := $(shell uname -m)

BUILD_DIR := ../build
INCLUDE_DIR := $(BUILD_DIR)/include

ifeq ($(UNAME_S),Darwin)
  ifeq ($(UNAME_M),arm64)
    LIB_DIR := $(BUILD_DIR)/moshi-mac/lib/aarch64
  else
    LIB_DIR := $(BUILD_DIR)/moshi-mac/lib/x86_64
  endif
  LDFLAGS := -L$(LIB_DIR) -lmoshi_ffi \
             -framework Accelerate -framework Metal -framework MetalPerformanceShaders \
             -lc++ -lm -lpthread
  CC := clang
else ifeq ($(UNAME_S),Linux)
  LIB_DIR := $(BUILD_DIR)/moshi-linux/lib
  LDFLAGS := -L$(LIB_DIR) -lmoshi_ffi \
             -lm -lpthread -ldl -lstdc++
  CC := gcc
endif

CFLAGS := -O2 -Wall -I$(INCLUDE_DIR)

# Default model paths (override with make MIMI_MODEL=... MOSHI_MODEL=...)
MIMI_MODEL ?= $(HOME)/.pixieai/models/mimi/model.safetensors
MOSHI_MODEL ?= $(HOME)/.pixieai/models/moshiko/model.safetensors

.PHONY: all clean run

all: test_moshi

test_moshi: test_moshi.c $(LIB_DIR)/libmoshi_ffi.a
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

run: test_moshi
	./test_moshi "$(MIMI_MODEL)" "$(MOSHI_MODEL)" test_output.wav

clean:
	rm -f test_moshi test_input.wav test_output.wav
