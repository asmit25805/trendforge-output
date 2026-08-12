#ifndef EXPERT_CACHE_H
#define EXPERT_CACHE_H

void *expert_cache_get(const char *expert_name);
int expert_cache_pin(const char *expert_name);
int expert_cache_unpin(const char *expert_name);

#endif // EXPERT_CACHE_H
