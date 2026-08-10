import path from 'path';
import os from 'os';
import fs from 'fs';
import http from 'http';
import supertest from 'supertest';
import { ReviewServer } from '../src/server';
import {
  Comment,
  Edit,
  ApiError,
  ServerInfo,
  generateUuid,
} from '../src/types';

describe('ReviewServer integration tests', () => {
  const tmpHome = fs.mkdtempSync(path.join(os.tmpdir(), 'review-sync-'));
  const originalHome = process.env.HOME;

  beforeAll(() => {
    process.env.HOME = tmpHome;
  });

  afterAll(() => {
    process.env.HOME = originalHome;
    fs.rmSync(tmpHome, { recursive: true, force: true });
  });

  test('starts server and returns info', async () => {
    const server = new ReviewServer();
    await server.start();
    const info = server.getInfo();
    expect(info.port).toBeGreaterThan(0);
    await server.stop();
  });
});
