const pages = ["Home", "Downloads", "Crawl", "Ranking", "History", "Settings", "About"];
let currentPage = "Home";
let snapshot = { queue: [], logs: [], history: [], engines: [], config: {} };

const nav = document.querySelector("#nav");
const page = document.querySelector("#page");
const logList = document.querySelector("#log-list");

for (const name of pages) {
  const button = document.createElement("button");
  button.className = "nav-item";
  button.textContent = name;
  button.onclick = () => {
    currentPage = name;
    render();
  };
  nav.appendChild(button);
}

document.querySelector("#toggle-log").onclick = () => {
  logList.hidden = !logList.hidden;
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

async function refresh() {
  try {
    snapshot = await api("/api/snapshot");
    render();
  } catch (error) {
    console.error(error);
  }
}

function render() {
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.toggle("active", item.textContent === currentPage);
  });
  renderMetrics();
  renderLogs();
  const renderer = {
    Home: renderHome,
    Downloads: renderDownloads,
    Crawl: renderCrawl,
    Ranking: renderRanking,
    History: renderHistory,
    Settings: renderSettings,
    About: renderAbout,
  }[currentPage];
  page.innerHTML = renderer();
  bindPageEvents();
}

function renderMetrics() {
  const queue = snapshot.queue || [];
  const running = queue.filter((job) => job.status === "running").length;
  const queued = queue.filter((job) => job.status === "pending").length;
  const done = queue.filter((job) => job.status === "success").length;
  const failed = queue.filter((job) => job.status === "failed").length;
  document.querySelector("#metric-running").textContent = running;
  document.querySelector("#metric-queued").textContent = queued;
  document.querySelector("#metric-done").textContent = done;
  document.querySelector("#metric-failed").textContent = failed;
  const active = queue.find((job) => job.status === "running");
  document.querySelector("#active-task").textContent = active
    ? `${active.engine_id}: ${active.title}`
    : "Idle";
}

function renderLogs() {
  const logs = (snapshot.logs || []).slice(-80).reverse();
  logList.innerHTML =
    logs
      .map(
        (log) => `
      <div class="log">
        <strong class="${escapeHtml(log.level)}">${escapeHtml(log.level)}</strong>
        <span>${escapeHtml(log.message)}</span>
        <small>${escapeHtml(log.engine_id || "")}</small>
      </div>
    `,
      )
      .join("") || `<div class="muted">ログはまだありません。</div>`;
}

function renderHome() {
  const queue = snapshot.queue || [];
  const engines = snapshot.engines || [];
  return `
    <div class="page-grid">
      <section class="card">
        <span class="eyebrow">Quick Download</span>
        <h1>URLを貼るだけ</h1>
        <textarea id="download-urls" placeholder="URL1&#10;URL2&#10;URL3"></textarea>
        <div class="actions">
          <button class="primary" id="start-download">Download</button>
          <button class="ghost" id="detect-first">Detect first URL</button>
        </div>
        <p id="detect-result" class="muted"></p>
      </section>
      <section class="card">
        <span class="eyebrow">Dashboard</span>
        <h2>現在の状態</h2>
        <div class="stat-grid">
          ${stat("Running", queue.filter((job) => job.status === "running").length)}
          ${stat("Queued", queue.filter((job) => job.status === "pending").length)}
          ${stat("Done", queue.filter((job) => job.status === "success").length)}
          ${stat("Failed", queue.filter((job) => job.status === "failed").length)}
          ${stat("Engines", engines.length)}
          ${stat("History", (snapshot.history || []).length)}
        </div>
      </section>
    </div>
  `;
}

function renderDownloads() {
  return `
    <section class="card">
      <span class="eyebrow">Downloads</span>
      <h1>ダウンロード管理</h1>
      <div class="table-tools">
        <input id="table-search" placeholder="検索" />
        <select id="state-filter">
          <option value="">すべて</option>
          <option value="running">running</option>
          <option value="pending">pending</option>
          <option value="success">success</option>
          <option value="failed">failed</option>
        </select>
      </div>
      <div class="table" id="download-table">${renderQueueRows(snapshot.queue || [])}</div>
    </section>
  `;
}

function renderCrawl() {
  return `
    <div class="page-grid">
      <section class="card">
        <span class="eyebrow">Crawler</span>
        <h1>85xo Crawl</h1>
        <label>Service</label>
        <select id="crawl-service">
          <option value="85xo">85xo</option>
          <option value="gofile">GoFile</option>
        </select>
        <label>Seed URL</label>
        <textarea id="crawl-seeds" placeholder="https://www.85xo.com/latest-updates/"></textarea>
        <label>期間</label>
        <input id="crawl-days" type="number" min="1" value="10" />
        <label>最大ページ</label>
        <input id="crawl-max-pages" type="number" min="1" value="50" />
        <div class="actions">
          <button class="primary" id="start-crawl">取得してDL</button>
          <button class="ghost" id="scan-crawl">取得のみ</button>
        </div>
      </section>
      <section class="card">
        <span class="eyebrow">Results</span>
        <h2>収集結果</h2>
        <div id="crawl-result" class="table">${renderHistoryRows("crawl")}</div>
      </section>
    </div>
  `;
}

function renderRanking() {
  return `
    <section class="card">
      <span class="eyebrow">Ranking</span>
      <h1>ランキング</h1>
      <p class="muted">既存 Engine にランキング入口がある場合のみ表示します。GoFile は既存 ranking_dl.py を検出済みです。</p>
      <div class="table">${renderHistoryRows("ranking")}</div>
    </section>
  `;
}

function renderHistory() {
  return `
    <section class="card">
      <span class="eyebrow">History</span>
      <h1>履歴</h1>
      <div class="table">${renderHistoryRows()}</div>
    </section>
  `;
}

function renderSettings() {
  const config = snapshot.config || {};
  return `
    <section class="card">
      <span class="eyebrow">Settings</span>
      <h1>設定</h1>
      <div class="stat-grid">
        ${stat("保存先", escapeHtml(config.output_dir || "downloads"))}
        ${stat("Threads", config.threads ?? 3)}
        ${stat("Retry", config.retry ?? 2)}
      </div>
      <pre>${escapeHtml(JSON.stringify(config, null, 2))}</pre>
    </section>
  `;
}

function renderAbout() {
  return `
    <section class="card">
      <span class="eyebrow">About</span>
      <h1>dler-kun</h1>
      <p>既存ダウンローダーを壊さず、URL判定、キュー、設定、ログ、UIを統合するダウンロードプラットフォームです。</p>
      <p class="muted">Version 0.1.0 / MIT License / GitHub Private Repository</p>
    </section>
  `;
}

function bindPageEvents() {
  const startDownload = document.querySelector("#start-download");
  if (startDownload) {
    startDownload.onclick = async () => {
      const urls = document.querySelector("#download-urls").value;
      await api("/api/download", {
        method: "POST",
        body: JSON.stringify({ urls }),
      });
      await refresh();
      currentPage = "Downloads";
      render();
    };
  }
  const detectFirst = document.querySelector("#detect-first");
  if (detectFirst) {
    detectFirst.onclick = async () => {
      const first = document
        .querySelector("#download-urls")
        .value.split(/\r?\n/)
        .find(Boolean);
      const result = first ? await api(`/api/detect?url=${encodeURIComponent(first)}`) : {};
      document.querySelector("#detect-result").textContent = result.message || "URLがありません";
    };
  }
  const startCrawl = document.querySelector("#start-crawl");
  const scanCrawl = document.querySelector("#scan-crawl");
  if (startCrawl) startCrawl.onclick = () => runCrawl(true);
  if (scanCrawl) scanCrawl.onclick = () => runCrawl(false);

  const search = document.querySelector("#table-search");
  const filter = document.querySelector("#state-filter");
  if (search && filter) {
    const update = () => {
      const text = search.value.toLowerCase();
      const state = filter.value;
      const rows = (snapshot.queue || []).filter((job) => {
        const matchesText = JSON.stringify(job).toLowerCase().includes(text);
        const matchesState = !state || job.status === state;
        return matchesText && matchesState;
      });
      document.querySelector("#download-table").innerHTML = renderQueueRows(rows);
    };
    search.oninput = update;
    filter.onchange = update;
  }
}

async function runCrawl(download) {
  const service = document.querySelector("#crawl-service").value;
  const seeds = document
    .querySelector("#crawl-seeds")
    .value.split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const days = Number(document.querySelector("#crawl-days").value || 10);
  const maxPages = Number(document.querySelector("#crawl-max-pages").value || 50);
  const result = await api("/api/crawl", {
    method: "POST",
    body: JSON.stringify({
      service,
      seeds,
      days,
      download,
      output_dir: service === "85xo" ? "downloads/85xo" : "downloads",
      options: { max_pages: maxPages },
    }),
  });
  document.querySelector("#crawl-result").innerHTML = renderCrawlItems(result.items || []);
  await refresh();
}

function renderQueueRows(rows) {
  return (
    rows
      .map(
        (job) => `
      <article class="row">
        <div class="thumb"></div>
        <div>
          <strong>${escapeHtml(job.title)}</strong>
          <div class="muted">${escapeHtml(job.output_dir || "")}</div>
          <div class="progress"><div class="bar" style="width:${Number(job.progress || 0)}%"></div></div>
        </div>
        <span class="badge ${escapeHtml(job.status)}">${escapeHtml(job.status)}</span>
        <span>${escapeHtml(job.engine_id)}</span>
        <small>${escapeHtml(job.updated_at || "")}</small>
      </article>
    `,
      )
      .join("") || `<p class="muted">まだジョブはありません。</p>`
  );
}

function renderHistoryRows(kind) {
  const rows = (snapshot.history || []).filter((item) => !kind || item.kind === kind);
  return (
    rows
      .slice(-100)
      .reverse()
      .map(
        (item) => `
      <article class="row">
        <div class="thumb"></div>
        <div>
          <strong>${escapeHtml(item.message || item.url || item.kind)}</strong>
          <div class="muted">${escapeHtml((item.files || []).join(", "))}</div>
        </div>
        <span class="badge ${escapeHtml(item.status)}">${escapeHtml(item.status)}</span>
        <span>${escapeHtml(item.engine_id || "")}</span>
        <small>${escapeHtml(item.kind || "")}</small>
      </article>
    `,
      )
      .join("") || `<p class="muted">履歴はまだありません。</p>`
  );
}

function renderCrawlItems(items) {
  return (
    items
      .map(
        (item) => `
      <article class="row">
        <div class="thumb"></div>
        <div>
          <strong>${escapeHtml(item.title || item.url)}</strong>
          <div class="muted">${escapeHtml(item.url)}</div>
        </div>
        <span class="badge">ready</span>
        <span>${escapeHtml(item.published_at || "")}</span>
        <small>${item.downloadable ? "DL可" : "不可"}</small>
      </article>
    `,
      )
      .join("") || `<p class="muted">収集結果はまだありません。</p>`
  );
}

function stat(label, value) {
  return `<div class="stat"><small class="muted">${label}</small><b>${value}</b></div>`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

refresh();
setInterval(refresh, 3000);
