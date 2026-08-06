import { createHmac, createSign, sign as nodeSign, createPrivateKey, KeyObject } from 'crypto';
import { SDKError } from '../types';
import { KeyType } from '../types';

/**
 * SignatureProvider handles request signing for different key types.
 * It supports HMAC (hex secret), RSA private keys, and Ed25519 private keys.
 */
export class SignatureProvider {
  private key: string | KeyObject;
  private keyType: KeyType;

  constructor(key: string | KeyObject, keyType: KeyType) {
    this.key = key;
    this.keyType = keyType;
  }

  /**
   * Sign a message according to the configured key type.
   * @param message The string to be signed.
   * @returns The signature as a string.
   */
  sign(message: string): string {
    switch (this.keyType) {
      case KeyType.HMAC:
        return createHmac('sha256', this.key as string).update(message).digest('hex');
      case KeyType.RSA:
        return createSign('RSA-SHA256').update(message).sign(this.key as KeyObject, 'base64');
      case KeyType.Ed25519:
        return nodeSign(null, Buffer.from(message), this.key as KeyObject).toString('base64');
      default:
        throw new SDKError('Unsupported key type', 400);
    }
  }
}
