import React from 'react';
import styles from './MonitorPanel.module.css';

interface MonitorPanelProps {
  monitors: Record<string, string>;
}

export default function MonitorPanel({ monitors }: MonitorPanelProps) {
  // Common core modules to ensure they show up even if not in dict yet
  const coreModules = ['planning', 'control', 'routing', 'perception', 'prediction', 'localization'];
  
  // Merge core with anything else currently reported
  const displayModules = Array.from(new Set([...coreModules, ...Object.keys(monitors)]));

  const getStatusColor = (status: string) => {
    switch(status) {
      case 'OK': return 'var(--accent-green)';
      case 'WARN': return '#f59e0b'; // amber
      case 'ERROR': 
      case 'FATAL': return 'var(--accent-red)';
      default: return '#64748b'; // slate/unknown
    }
  };

  return (
    <div className={`glass-panel ${styles.container}`}>
      <h3 className={styles.title}>Apollo Core Modules</h3>
      
      <div className={styles.monitorList}>
        {displayModules.map(modName => {
          const status = monitors[modName] || 'UNKNOWN';
          const color = getStatusColor(status);
          
          return (
            <div key={modName} className={styles.monitorItem}>
              <div className={styles.moduleName}>{modName}</div>
              <div className={styles.statusBadge} style={{ borderColor: color, color: color, backgroundColor: `${color}15` }}>
                <div className={styles.statusDot} style={{ backgroundColor: color, boxShadow: `0 0 8px ${color}` }} />
                {status}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
