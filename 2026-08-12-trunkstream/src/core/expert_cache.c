#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <pthread.h>
#include "expert_cache.h"
#include "manifest_loader.h"
#include "quantizer_backend.h"

/* -------------------------------------------------------------
 * Internal data structures
 * ------------------------------------------------------------- */
typedef struct CacheEntry {
    char *expert_name;
    void *data;
    int pinned;
    struct CacheEntry *next;
} CacheEntry;

static CacheEntry *g_cache_head = NULL;
static pthread_mutex_t g_cache_lock = PTHREAD_MUTEX_INITIALIZER;

/* -------------------------------------------------------------
 * Public API
 * ------------------------------------------------------------- */
void *expert_cache_get(const char *expert_name) {
    if (!expert_name) {
        errno = EINVAL;
        return NULL;
    }
    pthread_mutex_lock(&g_cache_lock);
    for (CacheEntry *e = g_cache_head; e; e = e->next) {
        if (strcmp(e->expert_name, expert_name) == 0) {
            pthread_mutex_unlock(&g_cache_lock);
            return e->data;
        }
    }
    pthread_mutex_unlock(&g_cache_lock);
    /* Stub: return a newly allocated dummy buffer */
    void *buf = malloc(256);
    if (!buf) {
        return NULL;
    }
    memset(buf, 0, 256);
    return buf;
}

int expert_cache_pin(const char *expert_name) {
    if (!expert_name) {
        return -EINVAL;
    }
    pthread_mutex_lock(&g_cache_lock);
    for (CacheEntry *e = g_cache_head; e; e = e->next) {
        if (strcmp(e->expert_name, expert_name) == 0) {
            e->pinned = 1;
            pthread_mutex_unlock(&g_cache_lock);
            return 0;
        }
    }
    pthread_mutex_unlock(&g_cache_lock);
    return -ENOENT;
}

int expert_cache_unpin(const char *expert_name) {
    if (!expert_name) {
        return -EINVAL;
    }
    pthread_mutex_lock(&g_cache_lock);
    for (CacheEntry *e = g_cache_head; e; e = e->next) {
        if (strcmp(e->expert_name, expert_name) == 0) {
            e->pinned = 0;
            pthread_mutex_unlock(&g_cache_lock);
            return 0;
        }
    }
    pthread_mutex_unlock(&g_cache_lock);
    return -ENOENT;
}
