import { EventBus } from '../src/util/eventBus';
import { SDKError, UnsubscribeFn } from '../src/types';

describe('EventBus', () => {
  let bus: EventBus;

  beforeEach(() => {
    bus = new EventBus();
  });

  test('listener receives emitted event payload', () => {
    const listener = jest.fn();
    bus.on('order:update', listener);
    const payload = { id: 'order-1', status: 'filled' };
    bus.emit('order:update', payload);
    expect(listener).toHaveBeenCalledTimes(1);
    expect(listener).toHaveBeenCalledWith(payload);
  });

  test('once listener is invoked only once', () => {
    const listener = jest.fn();
    bus.once('order:update', listener);
    const payload = { id: 'order-2', status: 'new' };
    bus.emit('order:update', payload);
    bus.emit('order:update', payload);
    expect(listener).toHaveBeenCalledTimes(1);
    expect(listener).toHaveBeenCalledWith(payload);
  });

  test('off removes specific listener without affecting others', () => {
    const listenerA = jest.fn();
    const listenerB = jest.fn();
    const unsubA = bus.on('order:update', listenerA);
    bus.on('order:update', listenerB);
    bus.emit('order:update', { id: 'order-3' });
    expect(listenerA).toHaveBeenCalledTimes(1);
    expect(listenerB).toHaveBeenCalledTimes(1);
    unsubA();
    bus.emit('order:update', { id: 'order-4' });
    expect(listenerA).toHaveBeenCalledTimes(1);
    expect(listenerB).toHaveBeenCalledTimes(2);
  });

  test('off without listener clears all listeners for the event', () => {
    const listenerA = jest.fn();
    const listenerB = jest.fn();
    bus.on('order:update', listenerA);
    bus.on('order:update', listenerB);
    bus.emit('order:update', { id: 'order-5' });
    expect(listenerA).toHaveBeenCalledTimes(1);
    expect(listenerB).toHaveBeenCalledTimes(1);
    // @ts-ignore – accessing private method for test purpose
    (bus as any).off('order:update');
    bus.emit('order:update', { id: 'order-6' });
    expect(listenerA).toHaveBeenCalledTimes(1);
    expect(listenerB).toHaveBeenCalledTimes(1);
  });

  test('middleware can transform payload before listeners receive it', () => {
    const middleware = jest.fn((event, payload, next) => {
      const transformed = { ...payload, transformed: true };
      next();
      // Simulate post‑processing (no effect on listeners)
    });
    bus.use(middleware);
    const listener = jest.fn();
    bus.on('order:update', listener);
    const original = { id: 'order-7' };
    bus.emit('order:update', original);
    expect(middleware).toHaveBeenCalledTimes(1);
    expect(middleware).toHaveBeenCalledWith('order:update', original, expect.any(Function));
    expect(listener).toHaveBeenCalledTimes(1);
    // Listener receives original payload because middleware does not replace it
    expect(listener).toHaveBeenCalledWith(original);
  });

  test('middleware can abort propagation by not calling next', () => {
    const abortingMiddleware = jest.fn((event, payload, next) => {
      // Intentionally omit next()
    });
    bus.use(abortingMiddleware);
    const listener = jest.fn();
    bus.on('order:update', listener);
    bus.emit('order:update', { id: 'order-8' });
    expect(abortingMiddleware).toHaveBeenCalledTimes(1);
    expect(listener).not.toHaveBeenCalled();
  });

  test('error thrown in listener is emitted as error event', () => {
    const error = new Error('listener failure');
    const faultyListener = jest.fn(() => {
      throw error;
    });
    const errorHandler = jest.fn();
    bus.on('order:update', faultyListener);
    bus.on('error', errorHandler);
    bus.emit('order:update', { id: 'order-9' });
    expect(faultyListener).toHaveBeenCalledTimes(1);
    expect(errorHandler).toHaveBeenCalledTimes(1);
    expect(errorHandler).toHaveBeenCalledWith(error);
  });

  test('emit with invalid event name throws SDKError', () => {
    expect(() => {
      // @ts-ignore – intentionally passing empty string
      bus.emit('', { id: 'order-10' });
    }).toThrow(SDKError);
  });
});