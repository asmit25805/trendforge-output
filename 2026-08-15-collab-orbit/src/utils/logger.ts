import { env } from 'process';
import { format } from 'util';

/**
 * Log levels in increasing order of severity.
 */
export enum LogLevel {
  Debug = 0,
  Info = 1,
  Warn = 2,
  Error = 3,
  Silent = 4,
}

/**
 * Mapping from LogLevel to its string representation.
 */
const levelNames: Record<LogLevel, string> = {
  [LogLevel.Debug]: 'DEBUG',
  [LogLevel.Info]: 'INFO',
  [LogLevel.Warn]: 'WARN',
  [LogLevel.Error]: 'ERROR',
  [LogLevel.Silent]: 'SILENT',
};

/**
 * Current log level – can be overridden via LOG_LEVEL env var.
 */
const currentLevel: LogLevel = (() => {
  const lvl = env.LOG_LEVEL?.toUpperCase();
  switch (lvl) {
    case 'DEBUG':
      return LogLevel.Debug;
    case 'INFO':
      return LogLevel.Info;
    case 'WARN':
      return LogLevel.Warn;
    case 'ERROR':
      return LogLevel.Error;
    case 'SILENT':
      return LogLevel.Silent;
    default:
      return LogLevel.Info;
  }
})();

/**
 * Core logger function.
 */
export const logger = {
  debug: (...args: unknown[]) => {
    if (currentLevel <= LogLevel.Debug) console.debug(`[${levelNames[LogLevel.Debug]}]`, format(...args));
  },
  info: (...args: unknown[]) => {
    if (currentLevel <= LogLevel.Info) console.info(`[${levelNames[LogLevel.Info]}]`, format(...args));
  },
  warn: (...args: unknown[]) => {
    if (currentLevel <= LogLevel.Warn) console.warn(`[${levelNames[LogLevel.Warn]}]`, format(...args));
  },
  error: (...args: unknown[]) => {
    if (currentLevel <= LogLevel.Error) console.error(`[${levelNames[LogLevel.Error]}]`, format(...args));
  },
};
