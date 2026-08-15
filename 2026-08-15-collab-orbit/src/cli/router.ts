import { ParsedCommand, CommandHandler } from '../types';
import { logger } from '../utils/logger';

/**
 * Error thrown when the command router cannot find a handler for a given command.
 */
export class CommandNotFoundError extends Error {
  constructor(command: string) {
    super(`Command "${command}" not found`);
    this.name = 'CommandNotFoundError';
  }
}

/**
 * Simple command router that maps command names to handlers.
 */
export class CommandRouter {
  private readonly handlers: Map<string, CommandHandler> = new Map();

  /** Register a handler for a command. */
  register(command: string, handler: CommandHandler): void {
    if (this.handlers.has(command)) {
      logger.warn(`Overriding existing handler for command "${command}"`);
    }
    this.handlers.set(command, handler);
  }

  /** Execute a parsed command. */
  async route(cmd: ParsedCommand): Promise<unknown> {
    const handler = this.handlers.get(cmd.command);
    if (!handler) {
      throw new CommandNotFoundError(cmd.command);
    }
    logger.debug(`Routing command "${cmd.command}" with args ${JSON.stringify(cmd.args)}`);
    return handler(cmd);
  }
}

/** Re‑export ParsedCommand for convenience. */
export { ParsedCommand };
