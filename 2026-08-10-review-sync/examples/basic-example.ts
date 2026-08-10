import { ReviewServer } from '../src/server';
import { generateUuid, Comment, Edit, ReviewBatch, ServerInfo, ApiError } from '../src/types';
import * as http from 'http';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';

/**
 * Reads the lock file written by ReviewServer to obtain connection details.
 */
function readServerInfo(): ServerInfo {
  const lockPath = path.join(os.homedir(), '.review-sync', 'lock.json');
  const raw = fs.readFileSync(lockPath, { encoding: 'utf-8' });
  return JSON.parse(raw) as ServerInfo;
}

// Demonstration of starting a server, reading its info, and shutting down.
(async () => {
  const server = new ReviewServer();
  await server.start();
  const info = server.getInfo();
  console.log('Server started on port', info.port);

  // Example: read the lock file directly.
  const lockInfo = readServerInfo();
  console.log('Lock file info:', lockInfo);

  // Clean up.
  await server.stop();
})();
