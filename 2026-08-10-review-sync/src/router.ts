import express, { Request, Response, NextFunction, Router } from 'express';
import {
  Comment,
  Edit,
  ReviewBatch,
  ApiError,
  generateUuid,
  ReviewSessionState,
} from './types';
import { ReviewServer } from './server';

/**
 * Retrieves the ReviewServer instance attached to the Express app.
 * The server sets itself on `app.locals.reviewServer` during construction.
 */
function getReviewServer(app: express.Application): ReviewServer {
  const server = app.locals.reviewServer as ReviewServer;
  if (!server) {
    throw new Error('ReviewServer not initialized on app.locals');
  }
  return server;
}

const router = Router();

// Example endpoint that returns basic server information.
router.get('/info', (req: Request, res: Response) => {
  try {
    const server = getReviewServer(req.app);
    const info = server.getInfo();
    res.json(info);
  } catch (err) {
    const apiError: ApiError = {
      code: 'SERVER_NOT_INITIALIZED',
      message: (err as Error).message,
    };
    res.status(500).json(apiError);
  }
});

// Additional routes (e.g., /batch, /anchor) would be added here.

export default router;
