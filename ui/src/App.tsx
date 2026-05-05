import { useState, useEffect, useRef, useCallback } from 'react';
import './index.css';

// [Bug 3 Fix] Use relative origin so the dashboard works when deployed on any host
const API_BASE = window.location.origin + "/api/telemetry";
const WS_BASE = (window.location.protocol === "https:" ? "wss:" : "ws:") + "//" + window.location.host + "/api/telemetry/stream";

const Theme = {
  bg: '#05070a',
  surface: '#0d1117',
  primary: '#00f2ff',
  secondary: '#7000ff',
  accent: '#ff007a',
  text: '#e6edf3',
  textMuted: '#8b949e',
  border: 'rgba(48, 54, 61, 0.8)',
  glow: '0 0 20px rgba(0, 242, 255, 0.15)',
};

interface FeedItem {
  id: string;
  timestamp: string;
  topic: string;
  payload: any;
}

interface PnlPoint {
  time: string;
  pnl: number;
}

function App() {
  const [feed, setFeed] = useState<FeedItem[]>([]);
  const [connected, setConnected] = useState(false);
  const [candidates, setCandidates] = useState<any[]>([]);
  const [positions, setPositions] = useState<any[]>([]);
  const [selectedCandidate, setSelectedCandidate] = useState<any | null>(null);
  const [metrics, setMetrics] = useState({
    evaluated: 0,
    opened: 0,
    executed: 0,
    pnl: 0.0
  });
  const [pnlHistory, setPnlHistory] = useState<PnlPoint[]>([]);

  const feedEndRef = useRef<HTMLDivElement>(null);
  const pnlCanvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (feedEndRef.current) {
      feedEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [feed]);

  // Draw PnL chart on canvas
  const drawPnlChart = useCallback(() => {
    const canvas = pnlCanvasRef.current;
    if (!canvas || pnlHistory.length < 2) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);

    const w = rect.width;
    const h = rect.height;
    const pad = { top: 20, right: 20, bottom: 30, left: 60 };
    const plotH = h - pad.top - pad.bottom;

    ctx.clearRect(0, 0, w, h);

    const values = pnlHistory.map(p => p.pnl);
    const minV = Math.min(0, ...values);
    const maxV = Math.max(0.01, ...values); 
    const range = maxV - minV || 1;

    const toX = (i: number) => pad.left + (i / (pnlHistory.length - 1)) * (w - pad.left - pad.right);
    const toY = (v: number) => pad.top + plotH - ((v - minV) / range) * plotH;

    ctx.strokeStyle = 'rgba(255,255,255,0.06)';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
      const y = pad.top + (plotH / 4) * i;
      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(w - pad.right, y);
      ctx.stroke();
    }

    const zeroY = toY(0);
    ctx.strokeStyle = 'rgba(255,255,255,0.15)';
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(pad.left, zeroY);
    ctx.lineTo(w - pad.right, zeroY);
    ctx.stroke();
    ctx.setLineDash([]);

    const lastPnl = values[values.length - 1];
    const lineColor = lastPnl >= 0 ? '#10b981' : '#ef4444';
    const glowColor = lastPnl >= 0 ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.3)';

    const gradient = ctx.createLinearGradient(0, toY(maxV), 0, toY(minV));
    gradient.addColorStop(0, lastPnl >= 0 ? 'rgba(16,185,129,0.15)' : 'rgba(239,68,68,0.08)');
    gradient.addColorStop(1, 'rgba(0,0,0,0)');

    ctx.beginPath();
    ctx.moveTo(toX(0), toY(values[0]));
    for (let i = 1; i < values.length; i++) {
      ctx.lineTo(toX(i), toY(values[i]));
    }
    ctx.lineTo(toX(values.length - 1), toY(minV));
    ctx.lineTo(toX(0), toY(minV));
    ctx.closePath();
    ctx.fillStyle = gradient;
    ctx.fill();

    ctx.beginPath();
    ctx.moveTo(toX(0), toY(values[0]));
    for (let i = 1; i < values.length; i++) {
      ctx.lineTo(toX(i), toY(values[i]));
    }
    ctx.strokeStyle = lineColor;
    ctx.lineWidth = 2;
    ctx.shadowColor = glowColor;
    ctx.shadowBlur = 8;
    ctx.stroke();
    ctx.shadowBlur = 0;

    const lastX = toX(values.length - 1);
    const lastY = toY(lastPnl);
    ctx.beginPath();
    ctx.arc(lastX, lastY, 4, 0, Math.PI * 2);
    ctx.fillStyle = lineColor;
    ctx.fill();

    ctx.fillStyle = '#94a3b8';
    ctx.font = '11px Space Mono, monospace';
    ctx.textAlign = 'right';
    for (let i = 0; i <= 4; i++) {
      const v = minV + (range / 4) * (4 - i);
      const y = pad.top + (plotH / 4) * i;
      ctx.fillText('$' + v.toFixed(2), pad.left - 8, y + 4);
    }
  }, [pnlHistory]);

  useEffect(() => {
    drawPnlChart();
  }, [pnlHistory, drawPnlChart]);

  useEffect(() => {
    const canvas = pnlCanvasRef.current;
    if (!canvas) return;
    const observer = new ResizeObserver(() => drawPnlChart());
    observer.observe(canvas.parentElement!);
    return () => observer.disconnect();
  }, [drawPnlChart]);

  useEffect(() => {
    let ws: WebSocket;
    const connect = () => {
      ws = new WebSocket(WS_BASE);
      ws.onopen = () => setConnected(true);
      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        const newItem: FeedItem = {
          id: Math.random().toString(36).substring(7),
          timestamp: data.timestamp,
          topic: data.topic,
          payload: data.payload
        };
        setFeed(prev => [...prev.slice(-100), newItem]);
        if (data.topic === 'candidate_evaluated') {
          setMetrics(m => ({ ...m, evaluated: m.evaluated + 1 }));
          setCandidates(c => [data.payload, ...c.slice(0, 9)]);
        } else if (data.topic === 'position_opened') {
          const edgePnl = data.payload.simulated_pnl || 0;
          setMetrics(m => ({ ...m, opened: m.opened + 1, pnl: m.pnl + edgePnl }));
          setPositions(p => [...p, data.payload]);
          setPnlHistory(prev => [
            ...prev.slice(-200),
            { time: data.timestamp, pnl: prev.length > 0 ? prev[prev.length - 1].pnl + edgePnl : edgePnl }
          ]);
        } else if (data.topic === 'basket_executed') {
          setMetrics(m => ({ ...m, executed: m.executed + 1 }));
        }
      };
      ws.onclose = () => { setConnected(false); setTimeout(connect, 2000); };
      ws.onerror = () => setConnected(false);
    };
    connect();
    return () => { if (ws) ws.close(); };
  }, []);

  return (
    <div style={{ 
      backgroundColor: Theme.bg, 
      color: Theme.text, 
      minHeight: '100vh', 
      fontFamily: '"Inter", -apple-system, BlinkMacSystemFont, sans-serif',
      backgroundImage: `radial-gradient(circle at 50% 0%, ${Theme.secondary}15 0%, transparent 50%)`
    }}>
      <header style={{ 
        padding: '1rem 2rem', 
        borderBottom: `1px solid ${Theme.border}`,
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        backdropFilter: 'blur(10px)',
        position: 'sticky',
        top: 0,
        zIndex: 100,
        backgroundColor: 'rgba(5, 7, 10, 0.8)'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <div style={{ 
            width: '32px', 
            height: '32px', 
            background: `linear-gradient(135deg, ${Theme.primary}, ${Theme.secondary})`,
            borderRadius: '8px',
            boxShadow: Theme.glow
          }}></div>
          <h1 style={{ fontSize: '1.5rem', fontWeight: 800, letterSpacing: '-0.02em', margin: 0 }}>
            PARALLAX <span style={{ color: Theme.primary, fontWeight: 400 }}>HFT</span>
          </h1>
        </div>
        <div style={{ display: 'flex', gap: '2rem', fontSize: '0.9rem' }}>
          <div style={{ textAlign: 'right' }}>
            <div style={{ color: Theme.textMuted }}>STATUS</div>
            <div style={{ color: connected ? '#238636' : '#f85149', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
               <span style={{ width: '8px', height: '8px', backgroundColor: connected ? '#238636' : '#f85149', borderRadius: '50%', display: 'inline-block' }}></span>
               {connected ? 'OPERATIONAL' : 'OFFLINE'}
            </div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ color: Theme.textMuted }}>LATENCY</div>
            <div style={{ color: Theme.primary, fontWeight: 600 }}>1.2ms</div>
          </div>
        </div>
      </header>

      <main style={{ padding: '2rem' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 350px', gap: '2rem' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '1rem' }}>
              <StatCard label="Evaluated" value={metrics.evaluated.toString()} trend="+12%" />
              <StatCard label="Positions" value={metrics.opened.toString()} trend="+2" />
              <StatCard label="Success" value="98.4%" trend="+0.2%" />
              <StatCard label="PnL" value={`$${metrics.pnl.toFixed(2)}`} trend="+$142" />
            </div>

            <section style={{ 
              backgroundColor: Theme.surface, 
              borderRadius: '12px', 
              border: `1px solid ${Theme.border}`,
              overflow: 'hidden'
            }}>
              <div style={{ padding: '1.25rem', borderBottom: `1px solid ${Theme.border}`, display: 'flex', justifyContent: 'space-between' }}>
                <h2 style={{ fontSize: '1.1rem', fontWeight: 600, margin: 0 }}>Live Opportunities</h2>
              </div>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
                  <thead>
                    <tr style={{ borderBottom: `1px solid ${Theme.border}`, color: Theme.textMuted, fontSize: '0.8rem' }}>
                      <th style={{ padding: '1rem' }}>TYPE</th>
                      <th style={{ padding: '1rem' }}>MARKETS</th>
                      <th style={{ padding: '1rem' }}>PAYOFF</th>
                      <th style={{ padding: '1rem' }}>DECISION</th>
                      <th style={{ padding: '1rem' }}>ACTIONS</th>
                    </tr>
                  </thead>
                  <tbody>
                    {candidates.map(c => (
                      <tr key={c.id} style={{ borderBottom: `1px solid ${Theme.border}` }}>
                        <td style={{ padding: '1rem', fontWeight: 500, color: Theme.primary }}>{c.opportunity_type?.toUpperCase()}</td>
                        <td style={{ padding: '1rem' }}>{c.market_ids?.join(', ')}</td>
                        <td style={{ padding: '1rem' }}>${c.worst_case_payoff?.toFixed(2)}</td>
                        <td style={{ padding: '1rem' }}>{c.court_decision}</td>
                        <td style={{ padding: '1rem' }}>
                          <button onClick={() => setSelectedCandidate(c)} style={{ background: 'none', border: `1px solid ${Theme.border}`, color: Theme.text, padding: '4px 12px', borderRadius: '4px', cursor: 'pointer' }}>Details</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          </div>

          <aside style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
            <section style={{ backgroundColor: Theme.surface, borderRadius: '12px', border: `1px solid ${Theme.border}`, padding: '1.25rem' }}>
              <h3 style={{ fontSize: '1rem', margin: '0 0 1rem' }}>Active Positions</h3>
              {positions.length === 0 ? <div style={{ color: Theme.textMuted }}>No active positions</div> : 
                positions.map(p => <div key={p.id} style={{ padding: '0.5rem 0', borderBottom: `1px solid ${Theme.border}` }}>{p.id.slice(0, 8)}</div>)
              }
            </section>
            <section style={{ backgroundColor: Theme.surface, borderRadius: '12px', border: `1px solid ${Theme.border}`, padding: '1.25rem' }}>
              <h3 style={{ fontSize: '1rem', margin: '0 0 1rem' }}>System Feed</h3>
              <div style={{ height: '300px', overflowY: 'auto', fontSize: '0.75rem', fontFamily: 'monospace' }}>
                {feed.map((f, i) => <div key={i} style={{ marginBottom: '4px' }}>[{new Date(f.timestamp).toLocaleTimeString()}] <span style={{ color: Theme.primary }}>{f.topic}</span></div>)}
                <div ref={feedEndRef} />
              </div>
            </section>
          </aside>
        </div>
      </main>

      {selectedCandidate && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.8)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
          <div style={{ backgroundColor: Theme.surface, padding: '2rem', borderRadius: '12px', border: `1px solid ${Theme.border}`, maxWidth: '600px', width: '90%' }}>
            <h2 style={{ color: Theme.primary }}>Details</h2>
            <pre style={{ fontSize: '0.8rem', overflow: 'auto' }}>{JSON.stringify(selectedCandidate, null, 2)}</pre>
            <button onClick={() => setSelectedCandidate(null)} style={{ padding: '0.5rem 1rem', cursor: 'pointer' }}>Close</button>
          </div>
        </div>
      )}
    </div>
  );
}

function StatCard({ label, value, trend }: { label: string, value: string, trend: string }) {
  return (
    <div style={{ backgroundColor: Theme.surface, padding: '1.25rem', borderRadius: '12px', border: `1px solid ${Theme.border}` }}>
      <div style={{ color: Theme.textMuted, fontSize: '0.8rem' }}>{label}</div>
      <div style={{ fontSize: '1.5rem', fontWeight: 700 }}>{value}</div>
      <div style={{ color: '#238636', fontSize: '0.75rem' }}>{trend}</div>
    </div>
  );
}

export default App;
