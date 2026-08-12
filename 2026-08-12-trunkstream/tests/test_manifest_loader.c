#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "manifest_loader.h"

/* Helper: create a temporary manifest file with known content.
 * Returns the path to the file; caller must free the returned string
 * and unlink the file after use. */
static char *create_temp_manifest(void) {
    const char *json =
        "{\n"
        "  \"model_name\": \"test-model\",\n"
        "  \"layers\": []\n"
        "}\n";
    char tmpl[] = "/tmp/manifestXXXXXX";
    int fd = mkstemp(tmpl);
    if (fd < 0) {
        return NULL;
    }
    write(fd, json, strlen(json));
    close(fd);
    return strdup(tmpl);
}

int main(void) {
    char *path = create_temp_manifest();
    assert(path != NULL);

    ModelManifest *manifest = load_manifest(path);
    assert(manifest != NULL);
    assert(manifest->model_name != NULL);
    assert(strcmp(manifest->model_name, "test-model") == 0);

    LayerDescriptor *desc = get_layer_descriptor(manifest, "nonexistent");
    assert(desc != NULL); /* stub returns a dummy descriptor */

    free(manifest->model_name);
    free(manifest);
    free(desc);
    unlink(path);
    free(path);
    return 0;
}
