/**
 * StatusBar component for connection status and flight statistics
 */

interface StatusBarProps {
  connectionStatus: 'disconnected' | 'connecting' | 'connected' | 'error';
  error: string | null;
  stats: {
    total: number;
    filtered: number;
    inAir: number;
    stale: number;
  };
  lastUpdate: Date | null;
}

export function StatusBar({
  connectionStatus,
  error,
  stats,
  lastUpdate,
}: StatusBarProps) {
  const getStatusColor = () => {
    switch (connectionStatus) {
      case 'connected':
        return '#4CAF50';
      case 'connecting':
        return '#FFC107';
      case 'error':
        return '#F44336';
      default:
        return '#9E9E9E';
    }
  };

  const getStatusText = () => {
    switch (connectionStatus) {
      case 'connected':
        return 'Connected';
      case 'connecting':
        return 'Connecting...';
      case 'error':
        return 'Error';
      default:
        return 'Disconnected';
    }
  };

  const formatLastUpdate = () => {
    if (!lastUpdate) return 'Never';
    const secondsAgo = Math.floor((Date.now() - lastUpdate.getTime()) / 1000);
    if (secondsAgo < 60) return `${secondsAgo}s ago`;
    const minutesAgo = Math.floor(secondsAgo / 60);
    return `${minutesAgo}m ago`;
  };

  return (
    <div
      style={{
        position: 'absolute',
        bottom: 20,
        left: 20,
        right: 20,
        background: 'rgba(0, 0, 0, 0.8)',
        color: 'white',
        padding: '15px 20px',
        borderRadius: '8px',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        zIndex: 1000,
        flexWrap: 'wrap',
        gap: '15px',
      }}
    >
      {/* Connection Status */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        <div
          style={{
            width: '12px',
            height: '12px',
            borderRadius: '50%',
            background: getStatusColor(),
          }}
        />
        <span>{getStatusText()}</span>
        {error && (
          <span style={{ color: '#F44336', fontSize: '0.9em' }}>
            {error}
          </span>
        )}
      </div>

      {/* Statistics */}
      <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap' }}>
        <div>
          <strong>Total:</strong> {stats.total}
        </div>
        <div>
          <strong>Filtered:</strong> {stats.filtered}
        </div>
        <div>
          <strong>In Air:</strong> {stats.inAir}
        </div>
        {stats.stale > 0 && (
          <div style={{ color: '#FFC107' }}>
            <strong>Stale:</strong> {stats.stale}
          </div>
        )}
        <div>
          <strong>Last Update:</strong> {formatLastUpdate()}
        </div>
      </div>
    </div>
  );
}
