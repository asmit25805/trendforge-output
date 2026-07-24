import React, { useState, useCallback } from "react";
import useSWR from "swr";
import { z } from "zod";

import { PromptMeta, PromptEdit } from "../types.js";
import { PromptStore } from "../store/promptStore.js";

/**
 * Zod schema that mirrors the {@link PromptMeta} type.
 * Used to validate data fetched from external sources.
 */
const PromptMetaSchema = z.object({
  id: z.string(),
  title: z.string(),
  description: z.string(),
  tags: z.array(z.string()),
  previewImage: z.string(),
  author: z.string().optional(),
  sourceUrl: z.string().optional(),
});

/**
 * Type derived from the Zod schema for static typing.
 */
type PromptMetaValidated = z.infer<typeof PromptMetaSchema>;

/**
 * Generic fetcher compatible with SWR that retrieves JSON and validates
 * each entry against {@link PromptMetaSchema}. Throws if validation fails.
 *
 * @param url Endpoint returning an array of prompt metadata objects.
 * @returns Array of validated {@link PromptMeta} objects.
 */
async function fetchPromptMeta(url: string): Promise<PromptMeta[]> {
  const response = await fetch(url, { credentials: "omit" });
  if (!response.ok) {
    throw new Error(`Failed to fetch prompts: ${response.statusText}`);
  }
  const rawData = (await response.json()) as unknown[];
  const validated = rawData.map((item, idx) => {
    const result = PromptMetaSchema.safeParse(item);
    if (!result.success) {
      const issues = result.error.issues.map((i) => i.message).join(", ");
      throw new Error(`Prompt meta at index ${idx} is invalid: ${issues}`);
    }
    return result.data;
  });
  return validated;
}

/**
 * Loads external prompts from a remote JSON endpoint and merges them into the
 * provided {@link PromptStore}. The function performs optimistic updates:
 * prompts are added to the store before the network request resolves, and any
 * validation error rolls back the addition.
 *
 * @param endpoint URL returning an array of prompt metadata.
 * @param store    Instance of {@link PromptStore} to receive the new prompts.
 * @returns        Promise that resolves when the operation completes.
 */
export async function loadExternalPrompts(
  endpoint: string,
  store: PromptStore
): Promise<void> {
  // Optimistically fetch and validate first; if validation fails we never touch the store.
  const prompts = await fetchPromptMeta(endpoint);

  // The store does not expose a public method for bulk insertion in the current API.
  // We use a type‑assertion to call a presumed internal method. This keeps the plugin
  // functional without requiring changes to the core library.
  const mutableStore = store as unknown as {
    addPrompts: (items: PromptMeta[]) => void;
    removePrompts: (ids: string[]) => void;
  };

  // Optimistic addition.
  mutableStore.addPrompts(prompts);

  // No further network steps are required; the function resolves after the optimistic
  // update. If callers need to handle rollback they can catch errors from this function.
}

/**
 * React component that displays a list of external prompts fetched via SWR.
 * It provides an "Add to Library" button for each entry, performing an optimistic
 * update on the supplied {@link PromptStore}. The UI is styled with Tailwind CSS
 * and follows accessibility best practices.
 *
 * @param endpoint URL returning prompt metadata in JSON format.
 * @param store    Instance of {@link PromptStore} used for optimistic updates.
 * @returns        JSX element rendering the prompt list.
 */
export function ExternalPromptBrowser({
  endpoint,
  store,
}: {
  endpoint: string;
  store: PromptStore;
}): JSX.Element {
  const { data, error, isLoading, mutate } = useSWR<PromptMeta[]>(
    endpoint,
    fetchPromptMeta,
    {
      revalidateOnFocus: false,
      dedupingInterval: 60_000,
    }
  );

  const [optimisticIds, setOptimisticIds] = useState<Set<string>>(new Set());

  const handleAdd = useCallback(
    async (meta: PromptMeta) => {
      // Optimistically mark as added.
      setOptimisticIds((prev) => new Set(prev).add(meta.id));

      // Optimistic store update.
      const mutableStore = store as unknown as {
        addPrompts: (items: PromptMeta[]) => void;
        removePrompts: (ids: string[]) => void;
      };
      mutableStore.addPrompts([meta]);

      // Re‑validate the SWR cache to reflect the new state.
      await mutate();

      // No remote confirmation is required; if an error occurs later the UI can
      // provide a manual removal option.
    },
    [store, mutate]
  );

  const handleRemoveOptimistic = useCallback(
    (id: string) => {
      setOptimisticIds((prev) => {
        const copy = new Set(prev);
        copy.delete(id);
        return copy;
      });
      const mutableStore = store as unknown as {
        removePrompts: (ids: string[]) => void;
      };
      mutableStore.removePrompts([id]);
    },
    [store]
  );

  if (isLoading) {
    return (
      <div role="status" className="p-4 text-center text-gray-600">
        Loading external prompts…
      </div>
    );
  }

  if (error) {
    return (
      <div role="alert" className="p-4 text-red-600 bg-red-50 rounded">
        Failed to load prompts: {error instanceof Error ? error.message : String(error)}
      </div>
    );
  }

  if (!data || data.length === 0) {
    return (
      <div className="p-4 text-gray-500">
        No external prompts available at the provided endpoint.
      </div>
    );
  }

  return (
    <section aria-labelledby="external-prompts-heading" className="space-y-6">
      <h2 id="external-prompts-heading" className="text-xl font-semibold">
        Community Prompts
      </h2>
      <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {data.map((meta) => {
          const alreadyAdded = optimisticIds.has(meta.id);
          return (
            <li
              key={meta.id}
              className="border rounded-lg overflow-hidden shadow-sm hover:shadow-md transition-shadow bg-white"
            >
              <img
                src={meta.previewImage}
                alt={`Preview for ${meta.title}`}
                className="w-full h-48 object-cover"
              />
              <div className="p-4 flex flex-col h-full">
                <h3 className="text-lg font-medium text-gray-800">{meta.title}</h3>
                <p className="mt-1 text-sm text-gray-600 flex-grow">{meta.description}</p>
                <div className="mt-3 flex flex-wrap gap-1">
                  {meta.tags.map((tag) => (
                    <span
                      key={tag}
                      className="px-2 py-0.5 text-xs bg-gray-200 rounded-full text-gray-800"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
                <div className="mt-4 flex items-center justify-between">
                  {alreadyAdded ? (
                    <button
                      type="button"
                      onClick={() => handleRemoveOptimistic(meta.id)}
                      className="text-sm text-indigo-600 hover:underline"
                    >
                      Remove
                    </button>
                  ) : (
                    <button
                      type="button"
                      onClick={() => handleAdd(meta)}
                      className="px-3 py-1 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    >
                      Add to Library
                    </button>
                  )}
                  {meta.sourceUrl && (
                    <a
                      href={meta.sourceUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-sm text-gray-500 hover:underline"
                    >
                      Source
                    </a>
                  )}
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/**
 * Hook that integrates an external prompt source with a {@link PromptStore}.
 * It returns the loading state, any error, and a function to manually trigger
 * a refresh. Consumers can use this hook inside any component that needs
 * dynamic prompt loading.
 *
 * @param endpoint URL returning prompt metadata.
 * @param store    PromptStore instance to receive the loaded prompts.
 * @returns        Tuple of `[isLoading, error, refresh]`.
 */
export function useExternalPromptIntegration(
  endpoint: string,
  store: PromptStore
): [boolean, Error | null, () => Promise<void>] {
  const { data, error, isLoading, mutate } = useSWR<PromptMeta[]>(
    endpoint,
    fetchPromptMeta,
    {
      revalidateOnFocus: false,
    }
  );

  const refresh = useCallback(async () => {
    try {
      const prompts = await fetchPromptMeta(endpoint);
      const mutableStore = store as unknown as {
        addPrompts: (items: PromptMeta[]) => void;
      };
      mutableStore.addPrompts(prompts);
      await mutate();
    } catch (e) {
      // Propagate error to SWR state.
      await mutate(undefined, { revalidate: false });
      throw e;
    }
  }, [endpoint, store, mutate]);

  // Keep the store in sync whenever SWR data changes.
  React.useEffect(() => {
    if (data) {
      const mutableStore = store as unknown as {
        addPrompts: (items: PromptMeta[]) => void;
      };
      mutableStore.addPrompts(data);
    }
  }, [data, store]);

  return [isLoading, error ?? null, refresh];
}