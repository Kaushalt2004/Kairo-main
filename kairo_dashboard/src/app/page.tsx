"use client";

import React, { useEffect, useState } from 'react';
import styles from './page.module.css';
import Speedometer from '../components/Speedometer';
import SteeringWheel from '../components/SteeringWheel';
import MonitorPanel from '../components/MonitorPanel';
import SimControl from '../components/SimControl';

// Match the Python Telemetry BaseModel
interface TelemetryData {
  speed: number;
  steering: number;
  brake: number;
  throttle: number;
  objects: number;
  pedestrians: number;
  lane_detected: boolean;
  camera_status: string;
  apollo_status: string;
  monitors: Record<string, string>;
}

const defaultTelemetry: TelemetryData = {
  speed: 0.0,
  steering: 0.0,
  brake: 0.0,
  throttle: 0.0,
  objects: 0,
  pedestrians: 0,
  lane_detected: false,
  camera_status: 'offline',
  apollo_status: 'offline',
  monitors: {},
};

export default function Home() {
  const [telemetry, setTelemetry] = useState<TelemetryData>(defaultTelemetry);
  const [wsConnected, setWsConnected] = useState(false);

  useEffect(() => {
    // Connect to Kairo Core API
    const ws = new WebSocket('ws://127.0.0.1:8000/ws/telemetry');

    ws.onopen = () => {
      console.log('Connected to Kairo Telemetry WebSocket');
      setWsConnected(true);
    };

    ws.onmessage = (event) => {
      try {
        const data: TelemetryData = JSON.parse(event.data);
        setTelemetry(data);
      } catch (err) {
        console.error('Failed to parse telemetry data', err);
      }
    };

    ws.onclose = () => {
      console.log('Disconnected from Kairo Telemetry WebSocket');
      setWsConnected(false);
    };

    return () => {
      ws.close();
    };
  }, []);

  return (
    <main className={styles.main}>
      <header className={styles.header}>
        <div className={styles.logoContainer}>
          <h1 className="text-gradient">KAIRO</h1>
          <span className={styles.subtitle}>ADAS Dashboard</span>
        </div>
        
        <div className={styles.statusContainer}>
          <div className={styles.statusBadge}>
            <div className={`${styles.statusDot} ${wsConnected ? styles.dotGreen : styles.dotRed}`} />
            <span>API {wsConnected ? 'Connected' : 'Disconnected'}</span>
          </div>
          <div className={styles.statusBadge}>
            <div className={`${styles.statusDot} ${telemetry.apollo_status.includes('OK') || telemetry.apollo_status.includes('Linked') ? styles.dotGreen : styles.dotRed}`} />
            <span>Cyber RT</span>
          </div>
        </div>
      </header>

      <div className={styles.dashboardGrid}>
        
        {/* Driving Controls Column */}
        <section className={styles.controlColumn}>
          <Speedometer 
            speed={telemetry.speed} 
            throttle={telemetry.throttle} 
            brake={telemetry.brake} 
          />
          <SteeringWheel 
            steering={telemetry.steering} 
          />
        </section>
        
        {/* Center / Perception Column */}
        <section className={styles.perceptionColumn}>
          <div className={`glass-panel ${styles.cameraView}`}>
            <div className={styles.cameraOverlay}>
              <h3 className={styles.panelTitle}>Perception Feed</h3>
              <p className={styles.cameraPlaceholder}>
                {telemetry.camera_status === 'online' 
                  ? 'Video stream active' 
                  : 'Awaiting Camera Feed...'}
              </p>
            </div>
          </div>
          
          <div style={{ marginTop: '1.5rem' }}>
            <SimControl />
          </div>
        </section>

        {/* Info Column */}
        <section className={styles.infoColumn}>
          
          <MonitorPanel monitors={telemetry.monitors || {}} />

          <div className={`glass-panel ${styles.infoPanel}`}>
            <h3 className={styles.panelTitle}>Environment Data</h3>
            
            <div className={styles.dataRow}>
              <span className={styles.dataLabel}>Objects Detected</span>
              <span className={styles.dataValue}>{telemetry.objects}</span>
            </div>
            
            <div className={styles.dataRow}>
              <span className={styles.dataLabel}>Lane Detected</span>
              <span className={styles.dataValue} style={{ color: telemetry.lane_detected ? 'var(--accent-green)' : 'var(--accent-red)' }}>
                {telemetry.lane_detected ? 'YES' : 'NO'}
              </span>
            </div>
          </div>
        </section>

      </div>
    </main>
  );
}
