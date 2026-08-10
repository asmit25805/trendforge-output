import { CLI } from '../src/cli';
import { ServerInfo, generateUuid } from '../src/types';
import { ReviewServer } from '../src/server';
import path from 'path';

describe('CLI integration tests', () => {
  const originalExit = process.exit;
  const originalConsoleError = console.error;
  const originalConsoleLog = console.log;

  afterAll(() => {
    process.exit = originalExit;
    console.error = originalConsoleError;
    console.log = originalConsoleLog;
  });

  test('CLI start command launches server without exiting', async () => {
    const cli = new CLI();
    const exitMock = jest.fn();
    process.exit = exitMock as any;
    const logMock = jest.spyOn(console, 'log').mockImplementation(() => {});

    await cli.run(['node', 'review-sync', 'start']);

    expect(exitMock).not.toHaveBeenCalled();
    expect(logMock).toHaveBeenCalled();
    logMock.mockRestore();
  });
});
