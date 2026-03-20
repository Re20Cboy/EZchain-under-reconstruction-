from __future__ import annotations


def build_local_panel_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>EZchain V2 Console</title>
  <style>
    :root {
      --bg: #f3efe7;
      --bg-accent: #e7f2ef;
      --card: rgba(255, 253, 248, 0.92);
      --ink: #1d2a2a;
      --muted: #68777b;
      --line: #d7ddd4;
      --accent: #165d52;
      --accent-soft: #d7ebe6;
      --danger: #8f2d2d;
      --ok: #1f6b46;
      --shadow: 0 14px 32px rgba(21, 35, 31, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(22, 93, 82, 0.1), transparent 26%),
        radial-gradient(circle at top right, rgba(122, 89, 28, 0.08), transparent 24%),
        linear-gradient(145deg, var(--bg), var(--bg-accent));
      font-family: "SF Mono", Menlo, Monaco, "Cascadia Mono", monospace;
    }
    .wrap {
      max-width: 1220px;
      margin: 0 auto;
      padding: 28px 18px 40px;
    }
    .hero {
      display: grid;
      grid-template-columns: 2fr 1fr;
      gap: 16px;
      margin-bottom: 16px;
    }
    .hero-card, .card {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 16px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(10px);
    }
    .eyebrow {
      color: var(--accent);
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      margin-bottom: 8px;
    }
    h1, h2, h3 { margin: 0; }
    h1 { font-size: 28px; line-height: 1.1; }
    h2 { font-size: 16px; margin-bottom: 12px; }
    .sub {
      margin-top: 10px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
    }
    .stats {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin-top: 14px;
    }
    .stat {
      background: var(--accent-soft);
      border-radius: 14px;
      padding: 12px;
      min-height: 88px;
    }
    .stat .label {
      font-size: 11px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.06em;
      margin-bottom: 6px;
    }
    .stat .value {
      font-size: 22px;
      font-weight: 700;
      line-height: 1.1;
      word-break: break-word;
    }
    .stat .hint {
      margin-top: 6px;
      font-size: 12px;
      color: var(--muted);
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(12, minmax(0, 1fr));
      gap: 14px;
    }
    .span-4 { grid-column: span 4; }
    .span-5 { grid-column: span 5; }
    .span-7 { grid-column: span 7; }
    .field-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }
    .inline-actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 10px;
    }
    label {
      display: block;
      font-size: 12px;
      color: var(--muted);
      margin-bottom: 5px;
    }
    input, textarea, button {
      width: 100%;
      font: inherit;
      border-radius: 12px;
    }
    input, textarea {
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.92);
      color: var(--ink);
      padding: 10px 12px;
    }
    textarea {
      min-height: 84px;
      resize: vertical;
    }
    button {
      width: auto;
      border: 0;
      cursor: pointer;
      background: var(--accent);
      color: white;
      padding: 10px 14px;
      transition: transform 120ms ease, opacity 120ms ease;
    }
    button.secondary {
      background: #e7ece8;
      color: var(--ink);
      border: 1px solid var(--line);
    }
    button:hover { transform: translateY(-1px); }
    button:disabled { opacity: 0.6; cursor: wait; transform: none; }
    .banner {
      display: none;
      border-radius: 14px;
      padding: 12px 14px;
      margin-bottom: 12px;
      font-size: 13px;
    }
    .banner.show { display: block; }
    .banner.ok { background: rgba(31, 107, 70, 0.12); color: var(--ok); }
    .banner.err { background: rgba(143, 45, 45, 0.12); color: var(--danger); }
    .banner.info { background: rgba(22, 93, 82, 0.12); color: var(--accent); }
    .muted {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
    }
    .mini-list {
      display: grid;
      gap: 8px;
      margin-top: 10px;
    }
    .mini-item {
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px 12px;
      background: rgba(255, 255, 255, 0.76);
    }
    .mini-item strong {
      display: block;
      font-size: 12px;
      margin-bottom: 3px;
    }
    .mini-item span {
      color: var(--muted);
      font-size: 12px;
      word-break: break-word;
    }
    .output {
      background: #0d1421;
      color: #dcfce7;
      padding: 12px;
      border-radius: 14px;
      overflow: auto;
      min-height: 300px;
      max-height: 420px;
      white-space: pre-wrap;
      word-break: break-word;
    }
    @media (max-width: 980px) {
      .hero { grid-template-columns: 1fr; }
      .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .field-grid { grid-template-columns: 1fr; }
      .span-4, .span-5, .span-7 { grid-column: span 12; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <div class="hero-card">
        <div class="eyebrow">EZchain V2 Default Console</div>
        <h1>Wallet, node and transaction flows in one local panel.</h1>
        <div class="sub">
          This is the lightweight V2 visual layer on top of the existing local service. It keeps CLI semantics intact,
          but makes the main user path visible: wallet setup, local funds, sends, receipts, node lifecycle and runtime state.
        </div>
        <div class="stats">
          <div class="stat">
            <div class="label">Protocol</div>
            <div class="value" id="stat-protocol">unknown</div>
            <div class="hint" id="stat-mode">mode pending</div>
          </div>
          <div class="stat">
            <div class="label">Available Balance</div>
            <div class="value" id="stat-balance">--</div>
            <div class="hint" id="stat-wallet">wallet not loaded</div>
          </div>
          <div class="stat">
            <div class="label">Node Status</div>
            <div class="value" id="stat-node">unknown</div>
            <div class="hint" id="stat-height">height --</div>
          </div>
          <div class="stat">
            <div class="label">Network</div>
            <div class="value" id="stat-network">testnet</div>
            <div class="hint" id="stat-bootstrap">bootstrap pending</div>
          </div>
        </div>
      </div>
      <div class="hero-card">
        <div class="eyebrow">Session</div>
        <div class="field-grid">
          <div>
            <label for="token">API Token</label>
            <input id="token" placeholder="X-EZ-Token (ezchain_cli.py auth show-token)" />
          </div>
          <div>
            <label for="password">Wallet Password</label>
            <input id="password" placeholder="password" type="password"/>
          </div>
        </div>
        <div class="inline-actions">
          <button class="secondary" onclick="saveSession()">Save Session</button>
          <button class="secondary" onclick="refreshDashboard()">Refresh Status</button>
        </div>
        <div class="sub">
          Token is required for POST routes and sensitive wallet queries.
          Send operations also require a nonce and client transaction id, both generated automatically here.
        </div>
      </div>
    </div>
    <div id="banner" class="banner"></div>
    <div class="grid">
      <div class="card span-4">
        <h2>Wallet</h2>
        <div class="field-grid">
          <div>
            <label for="name">Wallet Name</label>
            <input id="name" placeholder="name" value="default"/>
          </div>
          <div>
            <label for="wallet-address">Current Address</label>
            <input id="wallet-address" placeholder="address appears after load" readonly />
          </div>
        </div>
        <div style="margin-top:10px;">
          <label for="mnemonic">Mnemonic (for import)</label>
          <textarea id="mnemonic" placeholder="paste mnemonic only if importing"></textarea>
        </div>
        <div class="inline-actions">
          <button onclick="createWallet()">Create Wallet</button>
          <button class="secondary" onclick="importWallet()">Import Wallet</button>
          <button class="secondary" onclick="showWallet()">Load Summary</button>
          <button class="secondary" onclick="showBalance()">Refresh Balance</button>
          <button class="secondary" onclick="walletCheckpoints()">Checkpoints</button>
        </div>
        <div id="wallet-summary" class="mini-list"></div>
      </div>

      <div class="card span-4">
        <h2>Transactions</h2>
        <div class="field-grid">
          <div>
            <label for="recipient">Recipient</label>
            <input id="recipient" placeholder="recipient address"/>
          </div>
          <div>
            <label for="amount">Amount</label>
            <input id="amount" placeholder="amount" value="100"/>
          </div>
        </div>
        <div style="margin-top:10px;">
          <label for="client_tx_id">Client Tx ID</label>
          <input id="client_tx_id" placeholder="optional; auto-generated if blank"/>
        </div>
        <div class="inline-actions">
          <button onclick="faucet()">Faucet</button>
          <button onclick="sendTx()">Send</button>
          <button class="secondary" onclick="pendingTx()">Pending</button>
          <button class="secondary" onclick="receiptsTx()">Receipts</button>
          <button class="secondary" onclick="historyTx()">History</button>
        </div>
        <div id="tx-summary" class="mini-list"></div>
      </div>

      <div class="card span-4">
        <h2>Node & Network</h2>
        <div class="field-grid">
          <div>
            <label for="consensus">Consensus Nodes</label>
            <input id="consensus" value="1" />
          </div>
          <div>
            <label for="accounts">Account Nodes</label>
            <input id="accounts" value="1" />
          </div>
        </div>
        <div style="margin-top:10px;">
          <label for="start_port">Start Port</label>
          <input id="start_port" value="19500" />
        </div>
        <div class="inline-actions">
          <button onclick="nodeStart()">Start Node</button>
          <button class="secondary" onclick="nodeStatus()">Node Status</button>
          <button class="secondary" onclick="networkInfo()">Network Info</button>
          <button class="secondary" onclick="showMetrics()">Metrics</button>
          <button class="secondary" onclick="nodeStop()">Stop Node</button>
        </div>
        <div id="node-summary" class="mini-list"></div>
      </div>

      <div class="card span-5">
        <h2>Activity Views</h2>
        <div class="inline-actions">
          <button class="secondary" onclick="historyTx()">History View</button>
          <button class="secondary" onclick="receiptsTx()">Receipt View</button>
          <button class="secondary" onclick="pendingTx()">Pending View</button>
          <button class="secondary" onclick="walletCheckpoints()">Checkpoint View</button>
        </div>
        <div class="muted" style="margin-top:10px;">
          Recent items are summarized here for quick scanning. Full raw payloads always appear in the output panel.
        </div>
        <div id="activity-summary" class="mini-list"></div>
      </div>

      <div class="card span-7">
        <h2>Output</h2>
        <div class="muted">
          This panel shows the last raw API response. Use it for exact payload inspection while the summary cards keep the main path readable.
        </div>
        <pre id="out" class="output">Ready.</pre>
      </div>
    </div>
  </div>
<script>
const SESSION_KEY = "ezchain_local_panel_session";
const state = {
  lastWallet: null,
  lastBalance: null,
  lastNode: null,
  lastNetwork: null,
  lastMetrics: null,
  lastHistory: null,
  lastPending: null,
  lastReceipts: null,
  lastCheckpoints: null,
};

const output = document.getElementById("out");
const banner = document.getElementById("banner");

const out = (v) => {
  output.textContent = typeof v === "string" ? v : JSON.stringify(v, null, 2);
};
const token = () => document.getElementById("token").value.trim();
const password = () => document.getElementById("password").value;
const setText = (id, value) => {
  document.getElementById(id).textContent = value;
};
const showBanner = (message, kind = "info") => {
  banner.className = `banner show ${kind}`;
  banner.textContent = message;
};
const saveSession = () => {
  localStorage.setItem(SESSION_KEY, JSON.stringify({
    token: token(),
    password: password(),
    name: document.getElementById("name").value,
    recipient: document.getElementById("recipient").value,
    amount: document.getElementById("amount").value,
    clientTxId: document.getElementById("client_tx_id").value,
  }));
  showBanner("Session fields saved locally in this browser.", "info");
};
const loadSession = () => {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw);
    document.getElementById("token").value = parsed.token || "";
    document.getElementById("password").value = parsed.password || "";
    document.getElementById("name").value = parsed.name || "default";
    document.getElementById("recipient").value = parsed.recipient || "";
    document.getElementById("amount").value = parsed.amount || "100";
    document.getElementById("client_tx_id").value = parsed.clientTxId || "";
  } catch (_) {}
};
const headers = (json = true) => {
  const h = {};
  if (json) h["Content-Type"] = "application/json";
  const t = token();
  if (t) h["X-EZ-Token"] = t;
  return h;
};
const withTokenHeaders = (auth = false) => {
  const h = {};
  if (auth && token()) h["X-EZ-Token"] = token();
  return h;
};
const handlePayload = (label, payload, opts = {}) => {
  out(payload);
  if (opts.silent) {
    return payload;
  }
  if (payload.ok) {
    showBanner(`${label} succeeded.`, "ok");
  } else {
    const error = payload.error || {};
    showBanner(`${label} failed: ${error.code || "error"}${error.message ? ` - ${error.message}` : ""}`, "err");
  }
  return payload;
};
const renderMiniList = (id, items) => {
  const target = document.getElementById(id);
  if (!items.length) {
    target.innerHTML = '<div class="mini-item"><strong>No data yet</strong><span>Run an action to populate this panel.</span></div>';
    return;
  }
  target.innerHTML = items.map((item) => `<div class="mini-item"><strong>${item.title}</strong><span>${item.body}</span></div>`).join("");
};
async function get(url, auth = false, opts = {}) {
  const r = await fetch(url, { headers: withTokenHeaders(auth) });
  return handlePayload(`GET ${url}`, await r.json(), opts);
}
async function getSecure(url, opts = {}) {
  const h = headers(false);
  if (password()) h["X-EZ-Password"] = password();
  const r = await fetch(url, { headers: h });
  return handlePayload(`GET ${url}`, await r.json(), opts);
}
async function post(url, body, extraHeaders = {}, opts = {}) {
  const r = await fetch(url, {
    method: "POST",
    headers: { ...headers(true), ...extraHeaders },
    body: JSON.stringify(body),
  });
  return handlePayload(`POST ${url}`, await r.json(), opts);
}
function renderDashboard() {
  const wallet = state.lastWallet && state.lastWallet.ok ? state.lastWallet.data : null;
  const balance = state.lastBalance && state.lastBalance.ok ? state.lastBalance.data : null;
  const node = state.lastNode && state.lastNode.ok ? state.lastNode.data : null;
  const network = state.lastNetwork && state.lastNetwork.ok ? state.lastNetwork.data : null;
  const metrics = state.lastMetrics && state.lastMetrics.ok ? state.lastMetrics.data : null;
  const history = state.lastHistory && state.lastHistory.ok ? state.lastHistory.data.items || [] : [];
  const pending = state.lastPending && state.lastPending.ok ? state.lastPending.data.items || [] : [];
  const receipts = state.lastReceipts && state.lastReceipts.ok ? state.lastReceipts.data.items || [] : [];
  const checkpoints = state.lastCheckpoints && state.lastCheckpoints.ok ? state.lastCheckpoints.data.items || [] : [];

  setText("stat-protocol", balance?.protocol_version || "unknown");
  setText("stat-mode", network ? `mode ${network.mode || "unknown"}` : "mode pending");
  setText("stat-balance", balance ? String(balance.available_balance ?? "--") : "--");
  setText("stat-wallet", wallet?.address || "wallet not loaded");
  setText("stat-node", node?.status || "unknown");
  setText("stat-height", node?.backend ? `height ${node.backend.height}` : `height ${balance?.chain_height ?? "--"}`);
  setText("stat-network", network?.network || "testnet");
  const reachable = network?.bootstrap_probe?.reachable;
  const total = network?.bootstrap_probe?.total;
  setText("stat-bootstrap", reachable === undefined ? "bootstrap pending" : `${reachable}/${total} bootstrap reachable`);
  document.getElementById("wallet-address").value = wallet?.address || "";

  renderMiniList("wallet-summary", [
    { title: "Wallet", body: wallet ? `${wallet.name || "default"} · ${wallet.address}` : "Load wallet summary to view address and metadata." },
    { title: "Balance", body: balance ? `available ${balance.available_balance}, pending bundles ${balance.pending_bundle_count}, incoming ${balance.pending_incoming_transfer_count}` : "Balance data unavailable." },
    { title: "V2 Breakdown", body: balance?.v2_status_breakdown ? Object.entries(balance.v2_status_breakdown).map(([k, v]) => `${k}:${v}`).join(" · ") : "No V2 breakdown loaded." },
  ]);
  renderMiniList("tx-summary", [
    { title: "Receipts", body: receipts.length ? `latest seq ${receipts[receipts.length - 1].seq}, total ${receipts.length}` : "No receipt data loaded." },
    { title: "Pending", body: pending.length ? `${pending.length} pending item(s)` : "No pending items." },
    { title: "History", body: history.length ? `${history.length} history item(s), latest ${history[history.length - 1].status || "unknown"}` : "No history loaded." },
  ]);
  renderMiniList("node-summary", [
    { title: "Node", body: node ? `${node.status} · mode ${node.mode || "unknown"}` : "Node status not loaded." },
    { title: "Network", body: network ? `${network.network} · ${network.mode} · bootstrap ${network.bootstrap_nodes?.length || 0}` : "Network info not loaded." },
    { title: "Metrics", body: metrics ? `tx success ${metrics.transactions?.send_success ?? 0}, success rate ${metrics.transactions?.success_rate ?? 0}` : "Metrics not loaded." },
  ]);
  renderMiniList("activity-summary", [
    { title: "Recent History", body: history.length ? history.slice(-3).map((item) => `${item.status}:${item.amount}`).join(" | ") : "No history items." },
    { title: "Recent Receipts", body: receipts.length ? receipts.slice(-3).map((item) => `seq ${item.seq}@${item.height}`).join(" | ") : "No receipts." },
    { title: "Checkpoints", body: checkpoints.length ? `${checkpoints.length} checkpoint(s)` : "No checkpoints." },
  ]);
}
async function createWallet() {
  state.lastWallet = await post("/wallet/create", { name: document.getElementById("name").value, password: password() });
  await showWallet();
  saveSession();
}
async function importWallet() {
  state.lastWallet = await post("/wallet/import", {
    name: document.getElementById("name").value,
    password: password(),
    mnemonic: document.getElementById("mnemonic").value,
  });
  await showWallet();
  saveSession();
}
async function showWallet() {
  state.lastWallet = await get("/wallet/show");
  renderDashboard();
}
async function showBalance() {
  state.lastBalance = await getSecure("/wallet/balance");
  renderDashboard();
}
async function walletCheckpoints() {
  state.lastCheckpoints = await getSecure("/wallet/checkpoints");
  renderDashboard();
}
async function faucet() {
  state.lastBalance = await post("/tx/faucet", { amount: Number(document.getElementById("amount").value), password: password() });
  await showBalance();
  saveSession();
}
async function sendTx() {
  const clientTxId = document.getElementById("client_tx_id").value || crypto.randomUUID();
  document.getElementById("client_tx_id").value = clientTxId;
  await post(
    "/tx/send",
    {
      recipient: document.getElementById("recipient").value,
      amount: Number(document.getElementById("amount").value),
      password: password(),
      client_tx_id: clientTxId,
    },
    { "X-EZ-Nonce": crypto.randomUUID() }
  );
  await refreshDashboard();
  saveSession();
}
async function historyTx() {
  state.lastHistory = await get("/tx/history");
  renderDashboard();
}
async function pendingTx() {
  state.lastPending = await getSecure("/tx/pending");
  renderDashboard();
}
async function receiptsTx() {
  state.lastReceipts = await getSecure("/tx/receipts");
  renderDashboard();
}
async function showMetrics() {
  state.lastMetrics = await get("/metrics");
  renderDashboard();
}
async function networkInfo() {
  state.lastNetwork = await get("/network/info");
  renderDashboard();
}
async function nodeStart() {
  await post("/node/start", {
    consensus: Number(document.getElementById("consensus").value),
    accounts: Number(document.getElementById("accounts").value),
    start_port: Number(document.getElementById("start_port").value),
  });
  await nodeStatus();
}
async function nodeStatus() {
  state.lastNode = await get("/node/status");
  renderDashboard();
}
async function nodeStop() {
  await post("/node/stop", {});
  await nodeStatus();
}
async function refreshDashboard() {
  const tasks = [
    get("/wallet/show", false, { silent: true }).then((payload) => { state.lastWallet = payload; }),
    get("/node/status", false, { silent: true }).then((payload) => { state.lastNode = payload; }),
    get("/network/info", false, { silent: true }).then((payload) => { state.lastNetwork = payload; }),
    get("/metrics", false, { silent: true }).then((payload) => { state.lastMetrics = payload; }),
    get("/tx/history", false, { silent: true }).then((payload) => { state.lastHistory = payload; }),
  ];
  if (token() && password()) {
    tasks.push(getSecure("/wallet/balance", { silent: true }).then((payload) => { state.lastBalance = payload; }));
    tasks.push(getSecure("/tx/pending", { silent: true }).then((payload) => { state.lastPending = payload; }));
    tasks.push(getSecure("/tx/receipts", { silent: true }).then((payload) => { state.lastReceipts = payload; }));
    tasks.push(getSecure("/wallet/checkpoints", { silent: true }).then((payload) => { state.lastCheckpoints = payload; }));
  }
  await Promise.allSettled(tasks);
  renderDashboard();
}
loadSession();
refreshDashboard();
setInterval(() => { refreshDashboard(); }, 15000);
</script>
</body>
</html>
"""
