/**
 * MessagePack utilities (optional, for future use)
 * Currently using JSON, but this provides a placeholder for MessagePack support
 */

/**
 * Decode MessagePack message (placeholder - would require msgpack-lite or similar)
 * For now, we're using JSON only
 */
export function decodeMessagePack(_data: ArrayBuffer): unknown {
  // Placeholder - would implement with actual MessagePack library
  throw new Error('MessagePack not yet implemented');
}

/**
 * Check if WebSocket supports MessagePack protocol
 */
export function supportsMessagePack(protocols: string | null): boolean {
  if (!protocols) return false;
  return protocols.split(',').some((p) => p.trim() === 'msgpack');
}
