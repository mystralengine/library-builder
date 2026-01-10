/**
 * Skia Graphite Native Example
 *
 * This example demonstrates using Skia's Graphite rendering backend with Dawn
 * on native platforms (macOS, Linux, Windows). It uses GLFW for windowing and
 * Dawn's native backends (Metal, Vulkan, D3D12) for GPU acceleration.
 *
 * Build with: cmake -DUSE_NATIVE_GRAPHITE=ON
 */

// Include GLFW first
#include <GLFW/glfw3.h>

// Platform-specific GLFW native access
#if defined(__APPLE__)
    #define GLFW_EXPOSE_NATIVE_COCOA
    #include <GLFW/glfw3native.h>
    #include "metal_surface_helper.h"
#elif defined(_WIN32)
    #define GLFW_EXPOSE_NATIVE_WIN32
    #include <GLFW/glfw3native.h>
#elif defined(__linux__)
    #define GLFW_EXPOSE_NATIVE_X11
    #define GLFW_EXPOSE_NATIVE_WAYLAND
    #include <GLFW/glfw3native.h>
    // X11 headers define many macros that conflict with Dawn/WebGPU enums
    #undef Always
    #undef Success
    #undef None
    #undef Status
    #undef Bool
    #undef True
    #undef False
#endif

// Dawn native includes (must come AFTER X11 macro cleanup)
#include "dawn/dawn_proc.h"
#include "dawn/native/DawnNative.h"
#include "dawn/webgpu_cpp.h"

// Skia includes
#include "include/core/SkCanvas.h"
#include "include/core/SkColor.h"
#include "include/core/SkColorSpace.h"
#include "include/core/SkFont.h"
#include "include/core/SkPaint.h"
#include "include/core/SkPath.h"
#include "include/core/SkPathBuilder.h"
#include "include/core/SkRRect.h"
#include "include/core/SkSurface.h"
#include "include/effects/SkGradientShader.h"

// Skia Graphite includes
#include "include/gpu/graphite/BackendTexture.h"
#include "include/gpu/graphite/Context.h"
#include "include/gpu/graphite/ContextOptions.h"
#include "include/gpu/graphite/GraphiteTypes.h"
#include "include/gpu/graphite/Recorder.h"
#include "include/gpu/graphite/Recording.h"
#include "include/gpu/graphite/Surface.h"
#include "include/gpu/graphite/dawn/DawnBackendContext.h"
#include "include/gpu/graphite/dawn/DawnTypes.h"

#include <cmath>
#include <cstdio>
#include <memory>

// Global state
static std::unique_ptr<dawn::native::Instance> g_dawnInstance;
static std::unique_ptr<skgpu::graphite::Context> g_context;
static std::unique_ptr<skgpu::graphite::Recorder> g_recorder;
static wgpu::Instance g_instance;
static wgpu::Adapter g_adapter;
static wgpu::Device g_device;
static wgpu::Surface g_surface;
static wgpu::SurfaceConfiguration g_surfaceConfig;
static int g_width = 800;
static int g_height = 600;
static float g_time = 0.0f;
static GLFWwindow* g_window = nullptr;

// Forward declarations
bool initDawn();
bool initGraphite();
wgpu::Surface createSurface(GLFWwindow* window);
void render();
void cleanup();

// Error callback for GLFW
void glfwErrorCallback(int error, const char* description) {
    fprintf(stderr, "GLFW Error %d: %s\n", error, description);
}

// Window resize callback
void framebufferSizeCallback(GLFWwindow* window, int width, int height) {
    if (width > 0 && height > 0) {
        g_width = width;
        g_height = height;

        // Reconfigure surface with new size
        g_surfaceConfig.width = g_width;
        g_surfaceConfig.height = g_height;
        g_surface.Configure(&g_surfaceConfig);
    }
}

// Draw animated content demonstrating Skia Graphite
void drawContent(SkCanvas* canvas) {
    canvas->clear(SK_ColorWHITE);

    // Animated rotation for background
    canvas->save();
    canvas->translate(g_width / 2.0f, g_height / 2.0f);
    canvas->rotate(g_time * 30.0f);
    canvas->translate(-g_width / 2.0f, -g_height / 2.0f);

    // Draw a gradient background
    SkPaint bgPaint;
    bgPaint.setColor(SkColorSetRGB(230, 235, 255));
    canvas->drawRect(SkRect::MakeWH(g_width, g_height), bgPaint);

    canvas->restore();

    // Draw a simple path using SkPathBuilder
    SkPathBuilder pathBuilder;
    pathBuilder.moveTo(75.0f, 0.0f);
    pathBuilder.lineTo(150.0f, 50.0f);
    pathBuilder.lineTo(150.0f, 100.0f);
    pathBuilder.lineTo(75.0f, 50.0f);
    pathBuilder.close();

    pathBuilder.moveTo(75.0f, 50.0f);
    pathBuilder.lineTo(150.0f, 100.0f);
    pathBuilder.lineTo(150.0f, 150.0f);
    pathBuilder.lineTo(75.0f, 100.0f);
    pathBuilder.close();

    SkPath path = pathBuilder.detach();

    // Draw multiple shapes with animation
    for (int i = 0; i < 3; i++) {
        float offsetX = 100 + i * 200 + sin(g_time + i) * 20;
        float offsetY = 150 + cos(g_time * 0.5f + i) * 30;

        canvas->save();
        canvas->translate(offsetX, offsetY);
        canvas->scale(1.5f, 1.5f);

        // Shadow
        SkPaint shadowPaint;
        shadowPaint.setColor(SkColorSetARGB(60, 0, 0, 0));
        shadowPaint.setAntiAlias(true);
        canvas->save();
        canvas->translate(5, 5);
        canvas->drawPath(path, shadowPaint);
        canvas->restore();

        // Main shape with solid color
        SkPaint shapePaint;
        shapePaint.setAntiAlias(true);
        shapePaint.setColor(SkColorSetRGB(66, 133, 244));  // Blue
        canvas->drawPath(path, shapePaint);

        canvas->restore();
    }

    // Draw animated circles
    for (int i = 0; i < 5; i++) {
        float x = 100 + i * 150;
        float y = 450 + sin(g_time * 2.0f + i * 0.5f) * 50;
        float radius = 30 + sin(g_time * 3.0f + i) * 10;

        SkPaint circlePaint;
        circlePaint.setAntiAlias(true);
        circlePaint.setColor(SkColorSetARGB(
            180,
            (int)(128 + 127 * sin(g_time + i)),
            (int)(128 + 127 * cos(g_time + i * 0.7f)),
            (int)(128 + 127 * sin(g_time * 0.5f + i))
        ));
        canvas->drawCircle(x, y, radius, circlePaint);
    }

    // Draw rounded rectangles
    for (int i = 0; i < 4; i++) {
        float x = 50 + i * 180;
        float y = 300 + cos(g_time + i * 0.8f) * 30;

        SkPaint rectPaint;
        rectPaint.setAntiAlias(true);
        rectPaint.setColor(SkColorSetARGB(200,
            (int)(128 + 127 * cos(g_time * 0.5f + i)),
            200,
            (int)(128 + 127 * sin(g_time * 0.3f + i))
        ));

        SkRRect rrect = SkRRect::MakeRectXY(
            SkRect::MakeXYWH(x, y, 120, 60),
            15, 15
        );
        canvas->drawRRect(rrect, rectPaint);
    }

    // Draw text
    SkPaint textPaint;
    textPaint.setColor(SK_ColorBLACK);
    textPaint.setAntiAlias(true);

    SkFont font;
    font.setSize(24);

    canvas->drawString("Skia Graphite + Dawn (Native)", 50, 50, font, textPaint);

    char timeStr[64];
    snprintf(timeStr, sizeof(timeStr), "Time: %.1f  Size: %dx%d", g_time, g_width, g_height);
    canvas->drawString(timeStr, 50, 80, font, textPaint);

#if defined(__APPLE__)
    canvas->drawString("Backend: Metal", 50, 110, font, textPaint);
#elif defined(_WIN32)
    canvas->drawString("Backend: D3D12/Vulkan", 50, 110, font, textPaint);
#elif defined(__linux__)
    if (glfwGetPlatform() == GLFW_PLATFORM_WAYLAND) {
        canvas->drawString("Backend: Vulkan (Wayland)", 50, 110, font, textPaint);
    } else {
        canvas->drawString("Backend: Vulkan (X11)", 50, 110, font, textPaint);
    }
#endif
}

// Create platform-specific surface from GLFW window
wgpu::Surface createSurface(GLFWwindow* window) {
#if defined(__APPLE__)
    // macOS: Create Metal layer surface using the Objective-C++ helper
    void* cocoaWindow = glfwGetCocoaWindow(window);
    void* metalLayer = createMetalLayerForWindow(cocoaWindow);

    wgpu::SurfaceSourceMetalLayer metalSurfaceDesc;
    metalSurfaceDesc.layer = metalLayer;

    wgpu::SurfaceDescriptor surfaceDesc;
    surfaceDesc.nextInChain = &metalSurfaceDesc;
    return g_instance.CreateSurface(&surfaceDesc);

#elif defined(_WIN32)
    // Windows: Create HWND surface
    wgpu::SurfaceSourceWindowsHWND hwndSurfaceDesc;
    hwndSurfaceDesc.hinstance = GetModuleHandle(nullptr);
    hwndSurfaceDesc.hwnd = glfwGetWin32Window(window);

    wgpu::SurfaceDescriptor surfaceDesc;
    surfaceDesc.nextInChain = &hwndSurfaceDesc;
    return g_instance.CreateSurface(&surfaceDesc);

#elif defined(__linux__)
    // Linux: Detect platform at runtime (requires GLFW 3.4+)
    int platform = glfwGetPlatform();

    if (platform == GLFW_PLATFORM_WAYLAND) {
        // Wayland surface
        wgpu::SurfaceSourceWaylandSurface waylandSurfaceDesc;
        waylandSurfaceDesc.display = glfwGetWaylandDisplay();
        waylandSurfaceDesc.surface = glfwGetWaylandWindow(window);

        wgpu::SurfaceDescriptor surfaceDesc;
        surfaceDesc.nextInChain = &waylandSurfaceDesc;
        return g_instance.CreateSurface(&surfaceDesc);
    } else {
        // X11 surface (Xlib)
        wgpu::SurfaceSourceXlibWindow x11SurfaceDesc;
        x11SurfaceDesc.display = glfwGetX11Display();
        x11SurfaceDesc.window = static_cast<uint64_t>(glfwGetX11Window(window));

        wgpu::SurfaceDescriptor surfaceDesc;
        surfaceDesc.nextInChain = &x11SurfaceDesc;
        return g_instance.CreateSurface(&surfaceDesc);
    }
#endif
}

// Initialize Dawn native
bool initDawn() {
    printf("Initializing Dawn native...\n");

    // Set up Dawn proc table
    dawnProcSetProcs(&dawn::native::GetProcs());

    // Create Dawn instance with TimedWaitAny feature for proper synchronization
    wgpu::InstanceDescriptor instanceDesc = {};

    // Enable TimedWaitAny feature (needed for some synchronization operations)
    static const wgpu::InstanceFeatureName requiredFeatures[] = {
        wgpu::InstanceFeatureName::TimedWaitAny
    };
    instanceDesc.requiredFeatureCount = 1;
    instanceDesc.requiredFeatures = requiredFeatures;

    g_dawnInstance = std::make_unique<dawn::native::Instance>(&instanceDesc);
    g_instance = wgpu::Instance(g_dawnInstance->Get());

    if (!g_instance) {
        fprintf(stderr, "Failed to create Dawn instance\n");
        return false;
    }
    printf("Created Dawn instance\n");

    // Request adapter
    wgpu::RequestAdapterOptions adapterOptions = {};
    adapterOptions.powerPreference = wgpu::PowerPreference::HighPerformance;

    // Get adapters synchronously using dawn::native
    std::vector<dawn::native::Adapter> adapters = g_dawnInstance->EnumerateAdapters(&adapterOptions);
    if (adapters.empty()) {
        fprintf(stderr, "No suitable GPU adapter found\n");
        return false;
    }

    // Use the first available adapter
    g_adapter = wgpu::Adapter(adapters[0].Get());

    wgpu::AdapterInfo adapterInfo;
    g_adapter.GetInfo(&adapterInfo);
    printf("Using adapter: %.*s (%.*s)\n",
           static_cast<int>(adapterInfo.device.length),
           adapterInfo.device.data ? adapterInfo.device.data : "Unknown",
           static_cast<int>(adapterInfo.description.length),
           adapterInfo.description.data ? adapterInfo.description.data : "Unknown");

    // Create device
    wgpu::DeviceDescriptor deviceDesc = {};
    deviceDesc.SetDeviceLostCallback(
        wgpu::CallbackMode::AllowSpontaneous,
        [](const wgpu::Device& device, wgpu::DeviceLostReason reason, wgpu::StringView message) {
            fprintf(stderr, "Device lost: %s\n", std::string(message).c_str());
        }
    );
    deviceDesc.SetUncapturedErrorCallback(
        [](const wgpu::Device& device, wgpu::ErrorType type, wgpu::StringView message) {
            fprintf(stderr, "Dawn error (%d): %s\n", static_cast<int>(type), std::string(message).c_str());
        }
    );

    g_device = g_adapter.CreateDevice(&deviceDesc);
    if (!g_device) {
        fprintf(stderr, "Failed to create Dawn device\n");
        return false;
    }
    printf("Created Dawn device\n");

    return true;
}

// Initialize Skia Graphite with Dawn backend
bool initGraphite() {
    printf("Initializing Skia Graphite...\n");

    // Create surface from GLFW window
    g_surface = createSurface(g_window);
    if (!g_surface) {
        fprintf(stderr, "Failed to create surface\n");
        return false;
    }
    printf("Created surface\n");

    // Get surface capabilities
    wgpu::SurfaceCapabilities caps;
    g_surface.GetCapabilities(g_adapter, &caps);

    // Print available formats for debugging
    printf("Available surface formats (%zu):\n", caps.formatCount);
    for (size_t i = 0; i < caps.formatCount; i++) {
        printf("  Format %zu: %d\n", i, static_cast<int>(caps.formats[i]));
    }

    // Find a non-sRGB format (prefer BGRA8Unorm or RGBA8Unorm)
    // Fall back to sRGB if no non-sRGB format is available
    wgpu::TextureFormat chosenFormat = caps.formats[0];
    for (size_t i = 0; i < caps.formatCount; i++) {
        if (caps.formats[i] == wgpu::TextureFormat::BGRA8Unorm ||
            caps.formats[i] == wgpu::TextureFormat::RGBA8Unorm) {
            chosenFormat = caps.formats[i];
            break;
        }
    }

    // Configure surface
    g_surfaceConfig = {};
    g_surfaceConfig.device = g_device;
    g_surfaceConfig.format = chosenFormat;
    g_surfaceConfig.usage = wgpu::TextureUsage::RenderAttachment;
    g_surfaceConfig.width = g_width;
    g_surfaceConfig.height = g_height;
    g_surfaceConfig.presentMode = wgpu::PresentMode::Fifo;
    g_surfaceConfig.alphaMode = wgpu::CompositeAlphaMode::Opaque;

    g_surface.Configure(&g_surfaceConfig);
    printf("Configured surface (%dx%d, format=%d)\n", g_width, g_height, static_cast<int>(g_surfaceConfig.format));

    // Create Graphite backend context
    skgpu::graphite::DawnBackendContext backendContext;
    backendContext.fInstance = g_instance;
    backendContext.fDevice = g_device;
    backendContext.fQueue = g_device.GetQueue();
    // Use the native process events function (defined in DawnBackendContext.h)
    backendContext.fTick = skgpu::graphite::DawnNativeProcessEventsFunction;

    // Create Graphite context
    skgpu::graphite::ContextOptions options;
    g_context = skgpu::graphite::ContextFactory::MakeDawn(backendContext, options);
    if (!g_context) {
        fprintf(stderr, "Failed to create Graphite context\n");
        return false;
    }
    printf("Created Graphite context\n");

    // Create recorder
    g_recorder = g_context->makeRecorder();
    if (!g_recorder) {
        fprintf(stderr, "Failed to create recorder\n");
        return false;
    }
    printf("Created Graphite recorder\n");

    printf("Graphite initialization complete!\n");
    return true;
}

// Main rendering function
void render() {
    if (!g_context || !g_recorder || !g_surface) {
        return;
    }

    // Get the current surface texture
    wgpu::SurfaceTexture surfaceTexture;
    g_surface.GetCurrentTexture(&surfaceTexture);

    if (surfaceTexture.status != wgpu::SurfaceGetCurrentTextureStatus::SuccessOptimal &&
        surfaceTexture.status != wgpu::SurfaceGetCurrentTextureStatus::SuccessSuboptimal) {
        fprintf(stderr, "Failed to get current texture: %d\n", static_cast<int>(surfaceTexture.status));
        return;
    }

    // Create a texture view with explicit non-sRGB format if the surface is sRGB
    // This allows Skia to work with linear color values
    wgpu::TextureFormat viewFormat = g_surfaceConfig.format;
    if (viewFormat == wgpu::TextureFormat::BGRA8UnormSrgb) {
        viewFormat = wgpu::TextureFormat::BGRA8Unorm;
    } else if (viewFormat == wgpu::TextureFormat::RGBA8UnormSrgb) {
        viewFormat = wgpu::TextureFormat::RGBA8Unorm;
    }

    wgpu::TextureViewDescriptor viewDesc = {};
    viewDesc.format = viewFormat;
    wgpu::TextureView textureView = surfaceTexture.texture.CreateView(&viewDesc);
    if (!textureView) {
        fprintf(stderr, "Failed to create texture view\n");
        return;
    }

    // Create TextureInfo for the surface texture using the view format
    skgpu::graphite::DawnTextureInfo textureInfo(
        /*sampleCount=*/1,
        skgpu::Mipmapped::kNo,
        viewFormat,
        wgpu::TextureUsage::RenderAttachment,
        wgpu::TextureAspect::All
    );

    // Wrap the texture view in a BackendTexture
    skgpu::graphite::BackendTexture backendTexture =
        skgpu::graphite::BackendTextures::MakeDawn(
            SkISize::Make(g_width, g_height),
            textureInfo,
            textureView.Get()
        );

    if (!backendTexture.isValid()) {
        fprintf(stderr, "Failed to create backend texture\n");
        return;
    }

    // Determine SkColorType from surface format
    // Note: sRGB formats still use the same color type, color space handles the gamma
    SkColorType colorType;
    switch (g_surfaceConfig.format) {
        case wgpu::TextureFormat::BGRA8Unorm:
        case wgpu::TextureFormat::BGRA8UnormSrgb:
            colorType = kBGRA_8888_SkColorType;
            break;
        case wgpu::TextureFormat::RGBA8Unorm:
        case wgpu::TextureFormat::RGBA8UnormSrgb:
            colorType = kRGBA_8888_SkColorType;
            break;
        default:
            colorType = kBGRA_8888_SkColorType;
            break;
    }

    // Create SkSurface from the backend texture
    sk_sp<SkSurface> surface = SkSurfaces::WrapBackendTexture(
        g_recorder.get(),
        backendTexture,
        colorType,
        SkColorSpace::MakeSRGB(),
        nullptr  // surface props
    );

    if (!surface) {
        fprintf(stderr, "Failed to create SkSurface\n");
        return;
    }

    // Draw content
    SkCanvas* canvas = surface->getCanvas();
    drawContent(canvas);

    // Snap recording and submit to GPU
    std::unique_ptr<skgpu::graphite::Recording> recording = g_recorder->snap();
    if (recording) {
        skgpu::graphite::InsertRecordingInfo info;
        info.fRecording = recording.get();
        g_context->insertRecording(info);
        g_context->submit(skgpu::graphite::SyncToCpu::kNo);
    }

    // Present the surface
    g_surface.Present();

    // Process Dawn events
    g_instance.ProcessEvents();
}

// Cleanup resources
void cleanup() {
    g_recorder.reset();
    g_context.reset();
    g_surface = nullptr;
    g_device = nullptr;
    g_adapter = nullptr;
    g_instance = nullptr;
    g_dawnInstance.reset();

    if (g_window) {
        glfwDestroyWindow(g_window);
        g_window = nullptr;
    }
    glfwTerminate();
}

int main() {
    printf("Skia Graphite Native Example\n");
    printf("============================\n");

    // Initialize GLFW
    glfwSetErrorCallback(glfwErrorCallback);
    if (!glfwInit()) {
        fprintf(stderr, "Failed to initialize GLFW\n");
        return 1;
    }

    // Create window (no OpenGL context - we'll use Dawn/WebGPU)
    glfwWindowHint(GLFW_CLIENT_API, GLFW_NO_API);
    glfwWindowHint(GLFW_RESIZABLE, GLFW_TRUE);

    g_window = glfwCreateWindow(g_width, g_height, "Skia Graphite + Dawn", nullptr, nullptr);
    if (!g_window) {
        fprintf(stderr, "Failed to create GLFW window\n");
        glfwTerminate();
        return 1;
    }

    // Set up callbacks
    glfwSetFramebufferSizeCallback(g_window, framebufferSizeCallback);

    // Get actual framebuffer size (may differ on HiDPI displays)
    glfwGetFramebufferSize(g_window, &g_width, &g_height);
    printf("Window size: %dx%d\n", g_width, g_height);

    // Initialize Dawn
    if (!initDawn()) {
        fprintf(stderr, "Failed to initialize Dawn\n");
        cleanup();
        return 1;
    }

    // Initialize Graphite
    if (!initGraphite()) {
        fprintf(stderr, "Failed to initialize Graphite\n");
        cleanup();
        return 1;
    }

    // Main loop
    printf("Starting main loop...\n");
    while (!glfwWindowShouldClose(g_window)) {
        glfwPollEvents();

        render();

        // Update animation time (~60fps)
        g_time += 0.016f;
    }

    // Cleanup
    printf("Cleaning up...\n");
    cleanup();

    printf("Done!\n");
    return 0;
}
