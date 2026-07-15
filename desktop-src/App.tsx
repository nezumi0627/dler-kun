import { useEffect, useMemo, useState } from "react";

const API_BASE = "http://127.0.0.1:8787";

type QueueJob = {
  id: string;
  kind: string;
  engine_id: string;
  status: string;
  title: string;
  progress: number;
  speed: string;
  eta: string;
  output_dir: string;
  error: string;
};

type ProgressItem = {
  id: string;
  phase?: string;
  current_file?: string;
  completed_files?: number;
  total_files?: number;
  progress?: number;
  speed?: string;
  eta?: string;
  state?: string;
};

type CacheEntry = {
  key: string;
  url: string;
  path: string;
  status: string;
  size: number;
  engine_id?: string;
  error?: string;
  updated_at: string;
};

type LogEvent = {
  level: string;
  message: string;
  engine_id?: string;
  job_id?: string;
  created_at: string;
};

type Snapshot = {
  engines: Array<{ id: string; name: string }>;
  queue: QueueJob[];
  progress: ProgressItem[];
  logs: LogEvent[];
  history: Array<Record<string, unknown>>;
  cache: {
    summary: Record<string, number>;
    items: CacheEntry[];
  };
  config: Record<string, unknown>;
};

const emptySnapshot: Snapshot = {
  engines: [],
  queue: [],
  progress: [],
  logs: [],
  history: [],
  cache: { summary: {}, items: [] },
  config: {}
};

export function App() {
  const [snapshot, setSnapshot] = useState<Snapshot>(emptySnapshot);
  const [page, setPage] = useState("Home");
  const [urls, setUrls] = useState("");
  const [seed, setSeed] = useState("https://www.85xo.com/latest-updates/");
  const [days, setDays] = useState(10);
  const [outputDir, setOutputDir] = useState("downloads/85xo");
  const [busy, setBusy] = useState(false);
  const [apiError, setApiError] = useState("");

  async function refresh() {
    try {
      const data = await api<Snapshot>("/api/snapshot");
      setSnapshot(data);
      setApiError("");
    } catch (error) {
      setApiError(String(error));
    }
  }

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, 1500);
    return () => window.clearInterval(timer);
  }, []);

  const activeProgress = useMemo(
    () => snapshot.progress.find((item) => item.state === "running") ?? snapshot.progress.at(-1),
    [snapshot.progress]
  );

  const stats = useMemo(() => {
    const queue = snapshot.queue;
    return {
      running: queue.filter((job) => job.status === "running").length,
      pending: queue.filter((job) => job.status === "pending").length,
      success: queue.filter((job) => job.status === "success").length,
      failed: queue.filter((job) => job.status === "failed").length,
      cached: snapshot.cache.summary.complete ?? 0
    };
  }, [snapshot]);

  async function startDownload() {
    const list = urls.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    if (!list.length) return;
    await runAction(() =>
      api("/api/download/start", {
        method: "POST",
        body: JSON.stringify({ urls: list, output_dir: outputDir || undefined })
      })
    );
  }

  async function start85xoCrawl(download: boolean) {
    await runAction(() =>
      api("/api/crawl/start", {
        method: "POST",
        body: JSON.stringify({
          service: "85xo",
          seeds: seed ? [seed] : [],
          days,
          download,
          output_dir: outputDir,
          options: {
            method: "fast",
            max_pages: 50,
            resolve_workers: 6,
            parallel_downloads: 2,
            download_read_timeout: 30,
            download_attempts: 20
          }
        })
      })
    );
  }

  async function runAction(action: () => Promise<unknown>) {
    setBusy(true);
    try {
      await action();
      await refresh();
    } catch (error) {
      setApiError(String(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="shell">
      <aside className="side">
        <div className="brand">
          <div className="mark">D</div>
          <div>
            <strong>dler-kun</strong>
            <span>Desktop</span>
          </div>
        </div>
        {["Home", "Downloads", "Crawl", "Cache", "Logs", "Settings"].map((item) => (
          <button
            className={item === page ? "nav active" : "nav"}
            key={item}
            onClick={() => setPage(item)}
          >
            {item}
          </button>
        ))}
      </aside>

      <section className="content">
        <header className="topbar">
          <div>
            <span className="label">Active</span>
            <strong>{activeProgress?.current_file || activeProgress?.phase || "Idle"}</strong>
          </div>
          <div className="top-progress">
            <span>{Number(activeProgress?.progress ?? 0).toFixed(1)}%</span>
            <Progress value={Number(activeProgress?.progress ?? 0)} />
          </div>
          <div className="metrics-inline">
            <span>{activeProgress?.speed || "-"}</span>
            <span>ETA {activeProgress?.eta || "-"}</span>
          </div>
        </header>

        {apiError && <div className="error-banner">{apiError}</div>}

        {page === "Home" && (
          <div className="grid two">
            <section className="card">
              <h1>URL Download</h1>
              <textarea
                value={urls}
                onChange={(event) => setUrls(event.target.value)}
                placeholder="URLを複数行で貼り付け"
              />
              <input value={outputDir} onChange={(event) => setOutputDir(event.target.value)} />
              <button disabled={busy} className="primary" onClick={startDownload}>
                Download
              </button>
            </section>
            <Stats stats={stats} />
          </div>
        )}

        {page === "Downloads" && <Downloads queue={snapshot.queue} progress={snapshot.progress} />}
        {page === "Crawl" && (
          <section className="card">
            <h1>85xo Crawl</h1>
            <div className="form-grid">
              <label>
                Seed
                <input value={seed} onChange={(event) => setSeed(event.target.value)} />
              </label>
              <label>
                Days
                <input
                  type="number"
                  min={1}
                  value={days}
                  onChange={(event) => setDays(Number(event.target.value))}
                />
              </label>
              <label>
                Output
                <input value={outputDir} onChange={(event) => setOutputDir(event.target.value)} />
              </label>
            </div>
            <div className="actions">
              <button disabled={busy} className="primary" onClick={() => start85xoCrawl(true)}>
                収集してDL
              </button>
              <button disabled={busy} onClick={() => start85xoCrawl(false)}>
                収集のみ
              </button>
            </div>
          </section>
        )}
        {page === "Cache" && <Cache entries={snapshot.cache.items} summary={snapshot.cache.summary} />}
        {page === "Logs" && <Logs logs={snapshot.logs} />}
        {page === "Settings" && (
          <section className="card">
            <h1>Settings</h1>
            <pre>{JSON.stringify(snapshot.config, null, 2)}</pre>
          </section>
        )}
      </section>
    </main>
  );
}

function Stats({ stats }: { stats: Record<string, number> }) {
  return (
    <section className="card">
      <h1>Dashboard</h1>
      <div className="stats">
        {Object.entries(stats).map(([key, value]) => (
          <div className="stat" key={key}>
            <span>{key}</span>
            <strong>{value}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}

function Downloads({ queue, progress }: { queue: QueueJob[]; progress: ProgressItem[] }) {
  return (
    <section className="card">
      <h1>Downloads</h1>
      <div className="rows">
        {queue.map((job) => {
          const state = progress.find((item) => item.id === job.id);
          const value = Number(state?.progress ?? job.progress ?? 0);
          return (
            <article className="row" key={job.id}>
              <div>
                <strong>{job.title}</strong>
                <span>{state?.current_file || job.output_dir}</span>
              </div>
              <span className={`badge ${job.status}`}>{job.status}</span>
              <span>{job.engine_id}</span>
              <span>{state?.speed || job.speed || "-"}</span>
              <span>ETA {state?.eta || job.eta || "-"}</span>
              <Progress value={value} />
            </article>
          );
        })}
        {!queue.length && <p className="muted">ジョブはまだありません。</p>}
      </div>
    </section>
  );
}

function Cache({ entries, summary }: { entries: CacheEntry[]; summary: Record<string, number> }) {
  return (
    <section className="card">
      <h1>Download Cache</h1>
      <div className="summary">
        {["complete", "partial", "corrupt", "failed"].map((key) => (
          <span key={key}>
            {key}: <b>{summary[key] ?? 0}</b>
          </span>
        ))}
      </div>
      <div className="rows">
        {entries.slice().reverse().map((entry) => (
          <article className="row compact" key={entry.key}>
            <div>
              <strong>{entry.path}</strong>
              <span>{entry.url}</span>
            </div>
            <span className={`badge ${entry.status}`}>{entry.status}</span>
            <span>{formatBytes(entry.size)}</span>
          </article>
        ))}
      </div>
    </section>
  );
}

function Logs({ logs }: { logs: LogEvent[] }) {
  return (
    <section className="card">
      <h1>Logs</h1>
      <div className="rows">
        {logs.slice().reverse().map((log, index) => (
          <article className="log" key={`${log.created_at}-${index}`}>
            <span className={`level ${log.level}`}>{log.level}</span>
            <strong>{log.message}</strong>
            <span>{log.engine_id || ""}</span>
          </article>
        ))}
      </div>
    </section>
  );
}

function Progress({ value }: { value: number }) {
  return (
    <div className="progress">
      <div style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </div>
  );
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

function formatBytes(value: number) {
  if (!value) return "-";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}
