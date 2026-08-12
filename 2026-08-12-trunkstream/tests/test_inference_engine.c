#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "inference_engine.h"
#include "manifest_loader.h"
#include "expert_cache.h"
#include "trunk_streamer.h"
#include "quantizer_backend.h"

int main(void) {
    /* Create a minimal manifest for the engine */
    ModelManifest *manifest = calloc(1, sizeof(ModelManifest));
    manifest->model_name = strdup("dummy");

    /* Initialise dependent components */
    assert(trunk_streamer_init(manifest) == 0);
    assert(expert_cache_get("expert0") != NULL);

    /* Create a dummy engine instance */
    InferenceEngine engine = {0};

    /* Run the engine with a simple prompt */
    assert(engine_run(&engine, "Hello") == 0);
    assert(engine_step(&engine) == 0);
    engine_reset(&engine);

    trunk_streamer_shutdown();
    free(manifest->model_name);
    free(manifest);
    return 0;
}
