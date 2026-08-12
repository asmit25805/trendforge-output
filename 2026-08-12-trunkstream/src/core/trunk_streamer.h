#ifndef TRUNK_STREAMER_H
#define TRUNK_STREAMER_H

#include <stddef.h>

/* Forward declaration */
struct ModelManifest;

typedef struct ModelManifest ModelManifest;

int trunk_streamer_init(const ModelManifest *manifest);
int fetch_layer(const char *layer_name, void **out_buffer, size_t *out_size);
void trunk_streamer_shutdown(void);

#endif // TRUNK_STREAMER_H
