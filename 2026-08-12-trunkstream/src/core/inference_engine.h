#ifndef INFERENCE_ENGINE_H
#define INFERENCE_ENGINE_H

/* Forward declaration */
struct ModelManifest;

typedef struct ModelManifest ModelManifest;

typedef struct InferenceEngine InferenceEngine;

int engine_run(InferenceEngine *engine, const char *prompt);
int engine_step(InferenceEngine *engine);
void engine_reset(InferenceEngine *engine);

#endif // INFERENCE_ENGINE_H
