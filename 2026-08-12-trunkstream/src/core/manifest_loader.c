#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include "manifest_loader.h"

/* -------------------------------------------------------------
 * Internal data structures
 * ------------------------------------------------------------- */
typedef struct {
    char *path;
    uint64_t offset;
    size_t size;
} ShardInfo;

/* -------------------------------------------------------------
 * Public API
 * ------------------------------------------------------------- */
ModelManifest *load_manifest(const char *path) {
    if (!path) {
        errno = EINVAL;
        return NULL;
    }
    /* Minimal stub: in a real implementation this would parse JSON/YAML.
     * Here we allocate an empty ModelManifest so that the rest of the code
     * can compile and the unit tests can verify error handling.
     */
    ModelManifest *manifest = calloc(1, sizeof(ModelManifest));
    if (!manifest) {
        return NULL;
    }
    manifest->model_name = strdup("stub-model");
    return manifest;
}

LayerDescriptor *get_layer_descriptor(const ModelManifest *manifest, const char *layer_name) {
    (void)manifest; /* unused in stub */
    if (!layer_name) {
        errno = EINVAL;
        return NULL;
    }
    /* Return a dummy descriptor; real code would look up the layer.
     */
    LayerDescriptor *desc = calloc(1, sizeof(LayerDescriptor));
    return desc;
}
