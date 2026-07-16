import {
  ChangeSet,
  Policy,
  Verdict,
  WriteResult,
  ApplyResult,
  FileContentResult,
  ReadOpts,
} from "../types";

/**
 * Simple error type for policy evaluation failures.
 */
export class PolicyError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PolicyError";
  }
}

/**
 * Default minimal policy set – allows all changes.
 */
export const defaultPolicySet: Policy[] = [
  async (changeSet: ChangeSet): Promise<Verdict> => ({ allowed: true })
];

/**
 * Core engine that evaluates a ChangeSet against a collection of policies.
 */
export class PolicyEngine {
  private policies: Policy[];

  constructor(policies: Policy[] = defaultPolicySet) {
    this.policies = policies;
  }

  /**
   * Evaluate the provided ChangeSet against all configured policies.
   */
  async evaluate(changeSet: ChangeSet): Promise<Verdict> {
    const reasons: string[] = [];
    for (const policy of this.policies) {
      try {
        const verdict = await policy(changeSet);
        if (!verdict.allowed) {
          reasons.push(...(verdict.reasons ?? []));
        }
      } catch (err) {
        throw new PolicyError((err as Error).message);
      }
    }
    return { allowed: reasons.length === 0, reasons };
  }
}
