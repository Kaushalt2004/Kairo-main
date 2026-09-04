import React, { useState } from 'react';
import styles from './SimControl.module.css';

export default function SimControl() {
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  const sendCommand = async (action: string) => {
    setLoading(true);
    setStatus('Sending...');
    try {
      const res = await fetch('http://127.0.0.1:8000/api/sim_control', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action })
      });
      const data = await res.json();
      if (data.status === 'success') {
        setStatus(`Sent: ${action}`);
      } else {
        setStatus(`Error: ${data.message}`);
      }
    } catch (err) {
      setStatus(`Failed to reach API`);
    }
    setLoading(false);
    setTimeout(() => setStatus(null), 3000);
  };

  return (
    <div className={`glass-panel ${styles.container}`}>
      <h3 className={styles.title}>Sim Control</h3>
      
      <div className={styles.buttonGroup}>
        <button 
          className={`${styles.btn} ${styles.btnEngage}`}
          onClick={() => sendCommand('START')}
          disabled={loading}
        >
          Engage Auto
        </button>
        <button 
          className={`${styles.btn} ${styles.btnDisengage}`}
          onClick={() => sendCommand('RESET')}
          disabled={loading}
        >
          Disengage
        </button>
      </div>

      {status && <div className={styles.statusMsg}>{status}</div>}
    </div>
  );
}
