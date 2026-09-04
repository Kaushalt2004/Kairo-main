import React from 'react';
import styles from './Speedometer.module.css';

interface SpeedometerProps {
  speed: number;
  throttle: number;
  brake: number;
}

export default function Speedometer({ speed, throttle, brake }: SpeedometerProps) {
  // Cap speed display at 200 km/h for the dial math
  const displaySpeed = Math.min(Math.max(speed, 0), 200);
  // Calculate dash offset for a semi-circle SVG dial (circumference = PI * r)
  // Let r = 45, C ≈ 282.7. Semi-circle is 141.35.
  const circumference = 282.7;
  const strokeDashoffset = circumference - (displaySpeed / 200) * (circumference / 2);

  return (
    <div className={`glass-panel ${styles.container}`}>
      <h3 className={styles.title}>Velocity</h3>
      
      <div className={styles.dialContainer}>
        <svg viewBox="0 0 100 55" className={styles.svgDial}>
          {/* Background track */}
          <path
            d="M 5 50 A 45 45 0 0 1 95 50"
            fill="none"
            stroke="rgba(255,255,255,0.1)"
            strokeWidth="8"
            strokeLinecap="round"
          />
          {/* Active track */}
          <path
            d="M 5 50 A 45 45 0 0 1 95 50"
            fill="none"
            stroke="var(--accent-cyan)"
            strokeWidth="8"
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={strokeDashoffset}
            className={styles.activeTrack}
          />
        </svg>
        <div className={styles.speedDisplay}>
          <span className={styles.speedValue}>{speed.toFixed(1)}</span>
          <span className={styles.speedUnit}>km/h</span>
        </div>
      </div>

      <div className={styles.pedals}>
        <div className={styles.pedalGroup}>
          <span className={styles.pedalLabel}>Throttle</span>
          <div className={styles.barBg}>
            <div 
              className={styles.barFill} 
              style={{ width: `${throttle * 100}%`, backgroundColor: 'var(--accent-green)' }} 
            />
          </div>
        </div>
        
        <div className={styles.pedalGroup}>
          <span className={styles.pedalLabel}>Brake</span>
          <div className={styles.barBg}>
            <div 
              className={styles.barFill} 
              style={{ width: `${brake * 100}%`, backgroundColor: 'var(--accent-red)' }} 
            />
          </div>
        </div>
      </div>
    </div>
  );
}
