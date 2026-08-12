#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "manifest_loader.h"
#include "trunk_streamer.h"
#include "expert_cache.h"
#include "inference_engine.h"

int main(int argc, char *argv[]) {
    if (argc != 2) {
        fprintf(stderr, "Usage: %s <manifest_path>\n", argv[0]);
        return 1;
    }
    const char *manifest_path = argv[1];

    ModelManifest *manifest = load_manifest(manifest_path);
    if (!manifest) {
        fprintf(stderr, "Failed to load manifest: %s\n", manifest_path);
        return 1;
    }

    if (trunk_streamer_init(manifest) != 0) {
        fprintf(stderr, "Failed to initialise trunk streamer\n");
        return 1;
    }

    InferenceEngine engine = {0};
    const char *prompt = "Once upon a time";
    if (engine_run(&engine, prompt) != 0) {
        fprintf(stderr, "Inference failed\n");
        return 1;
    }

    printf("Inference completed for prompt: %s\n", prompt);

    trunk_streamer_shutdown();
    free(manifest->model_name);
    free(manifest);
    return 0;
}
