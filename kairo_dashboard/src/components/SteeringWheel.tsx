import React from 'react';
import styles from './SteeringWheel.module.css';

interface SteeringWheelProps {
  steering: number; // typically -100 to 100, or in radians/degrees depending on CARLA
}

export default function SteeringWheel({ steering }: SteeringWheelProps) {
  // CARLA steering is usually -1.0 to 1.0. Let's map it to degrees (-540 to 540 for a full wheel).
  // But for UI visualization, -180 to 180 is better so it doesn't spin wildly.
  const rotation = Math.max(-1, Math.min(1, steering)) * 180;

  return (
    <div className={`glass-panel ${styles.container}`}>
      <div className={styles.header}>
        <h3 className={styles.title}>Steering</h3>
        <span className={styles.angle}>{rotation.toFixed(1)}&deg;</span>
      </div>

      <div className={styles.wheelWrapper}>
        <div 
          className={styles.wheel}
          style={{ transform: `rotate(${rotation}deg)` }}
        >
          {/* A simple SVG steering wheel representation */}
          <svg viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
            <circle cx="50" cy="50" r="45" stroke="var(--foreground)" strokeWidth="6"/>
            {/* Center hub */}
            <circle cx="50" cy="50" r="12" fill="var(--foreground)"/>
            {/* Left spoke */}
            <path d="M50 50 L 5 50" stroke="var(--foreground)" strokeWidth="6"/>
            {/* Right spoke */}
            <path d="M50 50 L 95 50" stroke="var(--foreground)" strokeWidth="6"/>
            {/* Bottom spoke */}
            <path d="M50 50 L 50 95" stroke="var(--foreground)" strokeWidth="6"/>
            
            {/* Top marker indicator */}
            <path d="M50 5 L 50 15" stroke="var(--accent-red)" strokeWidth="8" strokeLinecap="round"/>
          </svg>
        </div>
      </div>
      
      <div className={styles.axisContainer}>
        <div className={styles.axisLine}>
          <div 
            className={styles.axisIndicator} 
            style={{ 
              left: `${50 + (steering * 50)}%`,
              backgroundColor: Math.abs(steering) > 0.1 ? 'var(--accent-cyan)' : 'var(--foreground)'
            }} 
          />
        </div>
        <div className={styles.axisLabels}>
          <span>L</span>
          <span>C</span>
          <span>R</span>
        </div>
      </div>
    </div>
  );
}
