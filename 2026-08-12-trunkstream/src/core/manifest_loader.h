#ifndef MANIFEST_LOADER_H
#define MANIFEST_LOADER_H

#include <stddef.h>
#include <stdint.h>

/* Forward declarations */
typedef struct ModelManifest ModelManifest;
typedef struct LayerDescriptor LayerDescriptor;

/* Public API */
ModelManifest *load_manifest(const char *path);
LayerDescriptor *get_layer_descriptor(const ModelManifest *manifest, const char *layer_name);

#endif // MANIFEST_LOADER_H
