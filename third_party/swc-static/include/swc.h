#ifdef __cplusplus
extern "C" {
#endif

// Returns 0 on success, non-zero on error. Output is heap-allocated and must be freed.
int swc_transpile_ts(const char* source,
                     const char* filename,
                     const char* source_map_mode, // "none" | "inline" | "file"
                     char** out_js,
                     char** out_sourcemap,
                     char** out_error);

// Free buffers allocated by SWC.
void swc_free(char* ptr);

#ifdef __cplusplus
} // extern "C"
#endif
