import { Client, Message, Channel, TextChannel, ThreadChannel } from 'discord.js';
import { EventPayload, Platform, TargetRef, MessageContent } from '../types.ts';
import { ChannelAdapter } from '../gateway/router.ts';

/**
 * DiscordAdapter implements the ChannelAdapter contract for Discord.
 * It translates Discord messages into the unified EventPayload and
 * posts responses back to Discord channels or threads.
 */
export class DiscordAdapter implements ChannelAdapter {
  /** Platform identifier for this adapter. */
  public readonly platform: Platform = Platform.Discord;

  /**
   * Constructs a new DiscordAdapter.
   * @param client Initialized discord.js Client with required intents.
   */
  constructor(private readonly client: Client) {}

  /**
   * Parses a raw Discord Message into a normalized EventPayload.
   * @param raw Discord Message object (or compatible shape).
   * @throws Error if required fields are missing or malformed.
   */
  public parseIncoming(raw: unknown): EventPayload {
    console.log('DiscordAdapter: parsing incoming payload');

    if (!(raw instanceof Message)) {
      throw new Error('DiscordAdapter.parseIncoming received non-Message object');
    }

    const message = raw as Message;

    // Determine if the message belongs to a thread.
    const threadId = this.extractThreadId(message);

    const payload: EventPayload = {
      platform: Platform.Discord,
      channelId: message.channel.id,
      threadId,
      userId: message.author.id,
      text: message.content,
      timestamp: message.createdTimestamp,
    };

    // Basic validation – mirrors GatewayRouter.validatePayload.
    if (!payload.channelId) {
      throw new Error('EventPayload missing channelId');
    }
    if (!payload.userId) {
      throw new Error('EventPayload missing userId');
    }
    if (typeof payload.text !== 'string') {
      throw new Error('EventPayload text must be a string');
    }
    if (typeof payload.timestamp !== 'number' || Number.isNaN(payload.timestamp)) {
      throw new Error('EventPayload timestamp must be a valid number');
    }

    console.log('DiscordAdapter: produced EventPayload', payload);
    return payload;
  }

  /**
   * Sends a message to a Discord channel or thread.
   * @param target Destination reference containing channel and optional thread.
   * @param content MessageContent to be delivered.
   */
  public async sendMessage(target: TargetRef, content: MessageContent): Promise<void> {
    console.log(`DiscordAdapter: sending message to channel ${target.channelId}${target.threadId ? ` thread ${target.threadId}` : ''}`);

    const sendFn = async () => {
      // Resolve the appropriate Discord channel (thread or base channel).
      const discordChannel = await this.resolveChannel(target);
      if (!discordChannel) {
        throw new Error(`DiscordAdapter.sendMessage could not resolve channel ${target.channelId}`);
      }

      // Prepare the payload for Discord.
      const discordPayload = {
        content: content.text,
        // Attachments are optional; discord.js expects an array of MessageAttachment-like objects.
        files: content.attachments?.map((att) => ({
          attachment: att.url,
          name: att.title ?? undefined,
        })),
      };

      // Send the message. Discord API may throw for rate limits or network issues.
      await discordChannel.send(discordPayload);
    };

    // Wrap the send operation with exponential back‑off retries.
    await this.withRetry(sendFn, 3);
    console.log('DiscordAdapter: message sent successfully');
  }

  /**
   * Extracts the thread identifier if the message is part of a thread.
   * Returns null for top‑level channel messages.
   */
  private extractThreadId(message: Message): string | null {
    // In discord.js, a thread is represented by ThreadChannel.
    if (message.channel instanceof ThreadChannel) {
      return message.channel.id;
    }
    // For messages posted in a thread via a parent channel reference.
    if (message.hasThread) {
      // message.channel may be a TextChannel with a thread reference.
      const thread = (message.channel as TextChannel).threads?.cache?.get(message.id);
      return thread?.id ?? null;
    }
    return null;
  }

  /**
   * Resolves a TargetRef to a Discord Channel (or ThreadChannel) instance.
   * @param target Target reference containing channelId and optional threadId.
   */
  private async resolveChannel(target: TargetRef): Promise<Channel | null> {
    // Prefer threadId if supplied; threads are separate channel objects.
    if (target.threadId) {
      const thread = await this.client.channels.fetch(target.threadId);
      if (thread && (thread instanceof ThreadChannel || thread instanceof TextChannel)) {
        return thread;
      }
    }

    // Fallback to the base channel.
    const baseChannel = await this.client.channels.fetch(target.channelId);
    if (baseChannel && (baseChannel instanceof TextChannel || baseChannel instanceof ThreadChannel)) {
      return baseChannel;
    }

    return null;
  }

  /**
   * Executes an async function with exponential back‑off retries.
   * Transient errors (network, rate limits) are retried up to `maxAttempts`.
   * @param fn Async operation to execute.
   * @param maxAttempts Maximum number of attempts (default 3).
   */
  private async withRetry<T>(fn: () => Promise<T>, maxAttempts: number = 3): Promise<T> {
    let attempt = 0;
    const baseDelay = 500; // milliseconds

    while (true) {
      try {
        attempt += 1;
        console.log(`DiscordAdapter: attempt ${attempt} of ${maxAttempts}`);
        return await fn();
      } catch (err) {
        const isTransient = this.isTransientError(err);
        console.error(`DiscordAdapter: attempt ${attempt} failed`, err);

        if (!isTransient || attempt >= maxAttempts) {
          console.error('DiscordAdapter: unrecoverable error or max attempts reached');
          throw err;
        }

        const delay = baseDelay * 2 ** (attempt - 1);
        console.log(`DiscordAdapter: waiting ${delay}ms before retry`);
        await new Promise((resolve) => setTimeout(resolve, delay));
      }
    }
  }

  /**
   * Determines whether an error is transient and worth retrying.
   * Checks for typical Discord API transient conditions.
   */
  private isTransientError(error: unknown): boolean {
    if (error instanceof Error) {
      const message = error.message.toLowerCase();
      // Rate limit, network hiccup, or temporary service outage.
      return (
        message.includes('rate limit') ||
        message.includes('network') ||
        message.includes('timeout') ||
        message.includes('temporarily unavailable')
      );
    }
    return false;
  }
}