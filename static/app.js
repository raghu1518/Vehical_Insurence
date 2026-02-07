// --- DOM ELEMENTS ---
const elements = {
    chatLog: document.getElementById("chat-log"),
    messageInput: document.getElementById("message"),
    sendBtn: document.getElementById("send"),
    resetBtn: document.getElementById("reset"),
    statusEl: document.getElementById("status"),
    sessionIdEl: document.getElementById("session-id"),
    langPill: document.getElementById("lang-pill"),
    transportPill: document.getElementById("transport-pill"),
    flowPill: document.getElementById("flow-pill"),
    phoneInput: document.getElementById("phone-number"),
    callUuidInput: document.getElementById("call-uuid"),
    promptSelect: document.getElementById("prompt-select"),
    promptEditor: document.getElementById("prompt-editor"),
    savePromptsBtn: document.getElementById("save-prompts"),
    configBox: document.getElementById("config-box"),
    dbTableSelect: document.getElementById("db-table-select"),
    dbLoadBtn: document.getElementById("db-load"),
    dbColumnsBtn: document.getElementById("db-columns"),
    dbRefreshBtn: document.getElementById("db-refresh"),
    dbFilterInput: document.getElementById("db-filter"),
    dbPageSize: document.getElementById("db-page-size"),
    dbPrevBtn: document.getElementById("db-prev"),
    dbNextBtn: document.getElementById("db-next"),
    dbPageInfo: document.getElementById("db-page-info"),
    dbTable: document.getElementById("db-table"),
    dbForm: document.getElementById("db-form"),
    dbModeInsert: document.getElementById("db-mode-insert"),
    dbModeUpdate: document.getElementById("db-mode-update"),
    dbMatchRow: document.getElementById("db-match-row"),
    dbMatchColumn: document.getElementById("db-match-column"),
    dbMatchValue: document.getElementById("db-match-value"),
    dbSaveBtn: document.getElementById("db-save"),
    dbCancelBtn: document.getElementById("db-cancel"),
    dbOutput: document.getElementById("db-output"),
    themeToggle: document.getElementById("theme-toggle"),
    toastContainer: document.getElementById("toast-container"),
    streamContainer: document.getElementById("stream-container"),
    
    // View Controllers
    deskChatBtn: document.getElementById("desk-chat-btn"),
    deskSettingsBtn: document.getElementById("desk-settings-btn"),
    deskDocsBtn: document.getElementById("desk-docs-btn"),
    deskDbBtn: document.getElementById("desk-db-btn"),
    mobileBtns: document.querySelectorAll(".mob-btn"),
    viewChat: document.getElementById("view-chat"),
    viewSettings: document.getElementById("view-settings"),
    viewDocs: document.getElementById("view-docs"),
    viewDb: document.getElementById("view-db")
};

let prompts = [];
const dbState = {
    columns: [],
    columnMeta: [],
    rows: [],
    limit: 50,
    offset: 0,
    filter: "",
    mode: "insert",
    selectedRow: null
};
let ws = null;

// --- VIEW NAVIGATION (MOBILE + DESKTOP) ---
function switchView(target) {
    const views = [elements.viewChat, elements.viewSettings, elements.viewDocs, elements.viewDb].filter(Boolean);
    views.forEach(view => {
        const active = view.id === target;
        view.classList.toggle('active-view', active);
        view.classList.toggle('view-hidden', !active);
    });

    elements.mobileBtns.forEach(btn => {
        btn.classList.toggle('active', btn.dataset.target === target);
    });

    if (elements.deskChatBtn) elements.deskChatBtn.classList.toggle('active', target === 'view-chat');
    if (elements.deskSettingsBtn) elements.deskSettingsBtn.classList.toggle('active', target === 'view-settings');
    if (elements.deskDocsBtn) elements.deskDocsBtn.classList.toggle('active', target === 'view-docs');
    if (elements.deskDbBtn) elements.deskDbBtn.classList.toggle('active', target === 'view-db');

    if (target === 'view-db') {
        loadDbTables();
    }
}

elements.mobileBtns.forEach(btn => {
    btn.addEventListener('click', () => switchView(btn.dataset.target));
});

elements.deskChatBtn.addEventListener('click', () => switchView('view-chat'));
if (elements.deskSettingsBtn) {
    elements.deskSettingsBtn.addEventListener('click', () => switchView('view-settings'));
}
if (elements.deskDocsBtn) {
    elements.deskDocsBtn.addEventListener('click', () => switchView('view-docs'));
}
if (elements.deskDbBtn) {
    elements.deskDbBtn.addEventListener('click', () => switchView('view-db'));
}


// --- THEME ENGINE ---
function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
    updateThemeIcon(next);
}

function updateThemeIcon(theme) {
    const icon = elements.themeToggle.querySelector('i');
    if(theme === 'dark') {
        icon.className = 'ri-moon-clear-line';
    } else {
        icon.className = 'ri-sun-line';
    }
}

// Init Icon
updateThemeIcon(localStorage.getItem('theme') || 'dark');
elements.themeToggle.addEventListener('click', toggleTheme);

// --- TOAST NOTIFICATIONS ---
function showToast(message, type = 'info') {
    // Limit max toasts to 3
    if (elements.toastContainer.childElementCount > 2) {
        elements.toastContainer.removeChild(elements.toastContainer.firstChild);
    }

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    
    let iconClass = 'ri-information-line';
    if(type === 'success') iconClass = 'ri-checkbox-circle-line';
    if(type === 'error') iconClass = 'ri-error-warning-line';
    
    toast.innerHTML = `<i class="${iconClass}"></i><span>${message}</span>`;
    elements.toastContainer.appendChild(toast);
    
    setTimeout(() => {
        toast.style.animation = 'fadeOut 0.3s forwards';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// --- UTILITIES ---
elements.messageInput.addEventListener('input', function() {
    this.style.height = 'auto';
    this.style.height = (this.scrollHeight) + 'px';
});

function ensureCallUuid() {
    if (elements.callUuidInput.value.trim()) return;
    if (crypto && crypto.randomUUID) {
        elements.callUuidInput.value = crypto.randomUUID();
    } else {
        elements.callUuidInput.value = 'uuid-' + Date.now();
    }
}

function setStatus(status) {
    if(status === 'connected') {
        elements.statusEl.classList.remove('disconnected');
        elements.statusEl.classList.add('connected');
        elements.statusEl.title = "System Online";
    } else {
        elements.statusEl.classList.remove('connected');
        elements.statusEl.classList.add('disconnected');
        elements.statusEl.title = "Offline / Error";
    }
}

function setTransport(mode) {
    if (!elements.transportPill) return;
    elements.transportPill.textContent = mode;
}

function connectWebSocket() {
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const wsUrl = `${proto}://${window.location.host}/ws`;
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        setStatus('connected');
        setTransport('WS');
    };

    ws.onclose = () => {
        setStatus('disconnected');
        setTransport('REST');
        setTimeout(connectWebSocket, 2000);
    };

    ws.onerror = () => {
        setStatus('disconnected');
        setTransport('REST');
    };

    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            if (data.type === "error") {
                showToast("Error processing request", "error");
                return;
            }
            if (data.type === "chat") {
                handleChatResponse(data);
            }
        } catch (e) {
            console.error("WS message parse failed", e);
        }
    };
}

function appendMessage(role, text) {
    const sysNode = document.querySelector('.system-node');
    if(sysNode) sysNode.remove();

    const div = document.createElement("div");
    div.className = `message ${role}`;
    div.textContent = text;
    elements.chatLog.appendChild(div);
    
    // Smooth Scroll to bottom using timeout to ensure layout render
    setTimeout(() => {
        elements.streamContainer.scrollTop = elements.streamContainer.scrollHeight;
    }, 50);
}

function handleChatResponse(data) {
    elements.sessionIdEl.textContent = data.call_uuid.substring(0, 8).toUpperCase();
    elements.langPill.textContent = data.language.toUpperCase();
    const flowName = data.flow && data.flow.name ? data.flow.name.toUpperCase() : "IDLE";
    elements.flowPill.textContent = flowName;
    appendMessage("bot", data.reply);
}

// --- NETWORK LOGIC ---
async function initSystem() {
    try {
        // Parallel fetch for speed
        const [cfgRes, pRes] = await Promise.all([
            fetch("/config"),
            fetch("/system")
        ]);

        const cfg = await cfgRes.json();
        elements.configBox.textContent = JSON.stringify(cfg, null, 2);

        const pData = await pRes.json();
        prompts = pData.prompts || [];
        
        elements.promptSelect.innerHTML = "";
        prompts.forEach(p => {
            const opt = document.createElement("option");
            opt.value = p.id;
            opt.textContent = p.name.toUpperCase();
            elements.promptSelect.appendChild(opt);
        });

        if(prompts.length) {
            elements.promptSelect.value = prompts[0].id;
            elements.promptEditor.value = prompts[0].prompt;
        }

        setStatus('connected');
        if (elements.dbPageSize) {
            dbState.limit = Number(elements.dbPageSize.value || 50);
        }
        await loadDbTables();
    } catch(e) {
        setStatus('disconnected');
        // Don't spam error toast on load, just set red status
        console.error("Init failed:", e);
    }
}

elements.promptSelect.addEventListener("change", () => {
    const p = prompts.find(x => x.id === elements.promptSelect.value);
    if(p) elements.promptEditor.value = p.prompt;
});

elements.savePromptsBtn.addEventListener("click", async () => {
    const p = prompts.find(x => x.id === elements.promptSelect.value);
    if(!p) return;
    
    p.prompt = elements.promptEditor.value;
    const originalText = elements.savePromptsBtn.textContent;
    elements.savePromptsBtn.textContent = "SAVING...";
    
    try {
        await fetch("/system", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({prompts})
        });
        showToast("System core updated", "success");
        elements.savePromptsBtn.textContent = originalText;
    } catch(e) {
        showToast("Save failed", "error");
        elements.savePromptsBtn.textContent = originalText;
    }
});

async function sendMessage(text, reset=false) {
    if(!text.trim()) return;
    if(!elements.phoneInput.value) {
        showToast("Target Phone Number Required", "error");
        elements.phoneInput.focus();
        return;
    }

    ensureCallUuid();
    appendMessage("user", text);
    
    // Reset Input
    elements.messageInput.value = "";
    elements.messageInput.style.height = 'auto';

    const payload = {
        message: text,
        phone_number: elements.phoneInput.value,
        call_uuid: elements.callUuidInput.value,
        system_prompt_id: elements.promptSelect.value,
        reset: reset
    };

    if (ws && ws.readyState === WebSocket.OPEN) {
        setTransport('WS');
        ws.send(JSON.stringify(payload));
        return;
    }

    try {
        setTransport('REST');
        const res = await fetch("/chat", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(payload)
        });

        const data = await res.json();
        if(!res.ok) {
            showToast(data.detail || "Error processing request", "error");
            appendMessage("bot", "Error encountered.");
            return;
        }
        handleChatResponse(data);
    } catch(e) {
        showToast("Network Error: Backend unreachable", "error");
        setStatus('disconnected');
    }
}

elements.sendBtn.addEventListener("click", () => sendMessage(elements.messageInput.value));

elements.resetBtn.addEventListener("click", () => {
    elements.chatLog.innerHTML = "";
    sendMessage("RESET SESSION", true);
    showToast("Session History Purged", "info");
});

elements.messageInput.addEventListener("keydown", (e) => {
    if(e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage(elements.messageInput.value);
    }
});

document.querySelectorAll(".macro-chip").forEach(btn => {
    btn.addEventListener("click", () => sendMessage(btn.dataset.message));
});

async function loadDbTables() {
    if (!elements.dbTableSelect) return;
    try {
        const res = await fetch("/db/tables");
        const data = await res.json();
        const tables = data.tables || [];
        elements.dbTableSelect.innerHTML = "";
        tables.forEach((t) => {
            const opt = document.createElement("option");
            opt.value = t;
            opt.textContent = t;
            elements.dbTableSelect.appendChild(opt);
        });
        if (!tables.length) {
            const opt = document.createElement("option");
            opt.value = "";
            opt.textContent = "No tables";
            elements.dbTableSelect.appendChild(opt);
            dbState.columns = [];
            dbState.rows = [];
            renderDbTable();
            if (elements.dbOutput) {
                elements.dbOutput.textContent = "No tables found.";
            }
            return;
        }
        if (tables.length) {
            elements.dbTableSelect.value = tables[0];
            await dbLoadColumns();
            await dbLoadRows();
        }
    } catch (e) {
        showToast("Unable to load DB tables", "error");
    }
}

function renderDbTable() {
    if (!elements.dbTable) return;
    const thead = elements.dbTable.querySelector("thead");
    const tbody = elements.dbTable.querySelector("tbody");
    if (!thead || !tbody) return;

    const filter = dbState.filter.trim().toLowerCase();
    let rows = dbState.rows || [];
    if (filter) {
        rows = rows.filter((row) => JSON.stringify(row).toLowerCase().includes(filter));
    }

    let columns = dbState.columns && dbState.columns.length ? dbState.columns : [];
    if (!columns.length && rows.length) {
        columns = Object.keys(rows[0]);
    }

    thead.innerHTML = "";
    tbody.innerHTML = "";

    const headRow = document.createElement("tr");
    if (columns.length) {
        columns.forEach((col) => {
            const th = document.createElement("th");
            th.textContent = col;
            headRow.appendChild(th);
        });
    } else {
        const th = document.createElement("th");
        th.textContent = "No columns";
        headRow.appendChild(th);
    }
    thead.appendChild(headRow);

    if (!rows.length) {
        const tr = document.createElement("tr");
        const td = document.createElement("td");
        td.textContent = "No rows";
        td.colSpan = Math.max(columns.length, 1);
        tr.appendChild(td);
        tbody.appendChild(tr);
        return;
    }

    rows.forEach((row) => {
        const tr = document.createElement("tr");
        if (dbState.selectedRow === row) {
            tr.classList.add("selected");
        }
        tr.addEventListener("click", () => {
            selectDbRow(row);
        });
        columns.forEach((col) => {
            const td = document.createElement("td");
            const value = row[col];
            if (value === null || value === undefined) {
                td.textContent = "";
            } else if (typeof value === "object") {
                td.textContent = JSON.stringify(value);
            } else {
                td.textContent = String(value);
            }
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
}

function updateDbPageInfo() {
    if (!elements.dbPageInfo) return;
    const page = Math.floor(dbState.offset / dbState.limit) + 1;
    elements.dbPageInfo.textContent = `Page ${page}`;
}

function setDbMode(mode) {
    dbState.mode = mode;
    if (elements.dbModeInsert) elements.dbModeInsert.classList.toggle("active", mode === "insert");
    if (elements.dbModeUpdate) elements.dbModeUpdate.classList.toggle("active", mode === "update");
    if (elements.dbMatchRow) elements.dbMatchRow.classList.toggle("hidden", mode !== "update");
    if (mode === "insert") {
        dbState.selectedRow = null;
        populateDbForm(null);
        if (elements.dbMatchValue) elements.dbMatchValue.value = "";
        renderDbTable();
    }
}

function renderDbForm() {
    if (!elements.dbForm) return;
    elements.dbForm.innerHTML = "";
    const cols = dbState.columnMeta || [];
    cols.forEach((col) => {
        const name = col.column_name || col.name || col;
        const field = document.createElement("div");
        field.className = "db-form-field";
        const label = document.createElement("label");
        label.textContent = name;
        const input = document.createElement("input");
        input.type = "text";
        input.dataset.column = name;
        input.placeholder = col.data_type ? String(col.data_type) : "";
        field.appendChild(label);
        field.appendChild(input);
        elements.dbForm.appendChild(field);
    });
    populateDbForm(dbState.selectedRow);
}

function populateDbForm(row) {
    if (!elements.dbForm) return;
    const inputs = elements.dbForm.querySelectorAll("input[data-column]");
    inputs.forEach((input) => {
        const col = input.dataset.column;
        if (row && col in row) {
            const value = row[col];
            input.value = value === null || value === undefined ? "" : String(value);
        } else {
            input.value = "";
        }
    });
}

function collectDbFormValues() {
    if (!elements.dbForm) return {};
    const inputs = elements.dbForm.querySelectorAll("input[data-column]");
    const data = {};
    inputs.forEach((input) => {
        const col = input.dataset.column;
        const value = input.value;
        if (value !== "") {
            data[col] = value;
        }
    });
    return data;
}

function selectDbRow(row) {
    dbState.selectedRow = row;
    setDbMode("update");
    populateDbForm(row);
    if (elements.dbMatchColumn && elements.dbMatchColumn.options.length) {
        if (!elements.dbMatchColumn.value) {
            elements.dbMatchColumn.value = elements.dbMatchColumn.options[0].value;
        }
    }
    if (elements.dbMatchColumn && elements.dbMatchValue) {
        const col = elements.dbMatchColumn.value;
        if (col && row && col in row) {
            elements.dbMatchValue.value = row[col] ?? "";
        }
    }
    renderDbTable();
}

async function dbLoadRows() {
    const table = elements.dbTableSelect.value;
    if (!table) return;
    try {
        const res = await fetch(`/db/table/${table}/rows?limit=${dbState.limit}&offset=${dbState.offset}`);
        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.detail || "DB error");
        }
        dbState.rows = data.rows || [];
        updateDbPageInfo();
        renderDbTable();
        elements.dbOutput.textContent = JSON.stringify(
            { rows: data.rows?.length || 0, limit: dbState.limit, offset: dbState.offset },
            null,
            2
        );
    } catch (e) {
        showToast("DB load failed", "error");
    }
}

async function dbLoadColumns() {
    const table = elements.dbTableSelect.value;
    if (!table) return;
    try {
        const res = await fetch(`/db/table/${table}/columns`);
        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.detail || "DB error");
        }
        dbState.columnMeta = data.columns || [];
        dbState.columns = dbState.columnMeta.map((c) => c.column_name || c.column);
        if (elements.dbMatchColumn) {
            elements.dbMatchColumn.innerHTML = "";
            dbState.columns.forEach((col) => {
                const opt = document.createElement("option");
                opt.value = col;
                opt.textContent = col;
                elements.dbMatchColumn.appendChild(opt);
            });
        }
        if (elements.dbMatchRow) {
            elements.dbMatchRow.classList.toggle("hidden", dbState.mode !== "update");
        }
        renderDbForm();
        renderDbTable();
        elements.dbOutput.textContent = JSON.stringify(data, null, 2);
    } catch (e) {
        showToast("Column fetch failed", "error");
    }
}

async function dbSave() {
    const table = elements.dbTableSelect.value;
    if (!table) return;
    const values = collectDbFormValues();
    if (dbState.mode === "insert") {
        if (!Object.keys(values).length) {
            showToast("Add at least one field before saving", "error");
            return;
        }
        try {
            const res = await fetch(`/db/table/${table}/rows`, {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({ data: values })
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || "DB error");
            elements.dbOutput.textContent = JSON.stringify(data, null, 2);
            await dbLoadRows();
            showToast("Row inserted", "success");
        } catch (e) {
            showToast("Insert failed", "error");
        }
    } else {
        const matchCol = elements.dbMatchColumn?.value;
        const matchVal = elements.dbMatchValue?.value;
        if (!matchCol || matchVal === undefined || matchVal === "") {
            showToast("Select match column/value for update", "error");
            return;
        }
        if (!Object.keys(values).length) {
            showToast("Add fields to update", "error");
            return;
        }
        try {
            const res = await fetch(`/db/table/${table}/rows`, {
                method: "PUT",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({ set: values, where: { [matchCol]: matchVal } })
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || "DB error");
            elements.dbOutput.textContent = JSON.stringify(data, null, 2);
            await dbLoadRows();
            showToast("Row updated", "success");
        } catch (e) {
            showToast("Update failed", "error");
        }
    }
}

function dbCancel() {
    dbState.selectedRow = null;
    setDbMode("insert");
    populateDbForm(null);
    if (elements.dbMatchValue) elements.dbMatchValue.value = "";
    renderDbTable();
}

if (elements.dbLoadBtn) elements.dbLoadBtn.addEventListener("click", dbLoadRows);
if (elements.dbColumnsBtn) elements.dbColumnsBtn.addEventListener("click", dbLoadColumns);
if (elements.dbRefreshBtn) elements.dbRefreshBtn.addEventListener("click", loadDbTables);
if (elements.dbSaveBtn) elements.dbSaveBtn.addEventListener("click", dbSave);
if (elements.dbCancelBtn) elements.dbCancelBtn.addEventListener("click", dbCancel);
if (elements.dbModeInsert) elements.dbModeInsert.addEventListener("click", () => setDbMode("insert"));
if (elements.dbModeUpdate) elements.dbModeUpdate.addEventListener("click", () => setDbMode("update"));
if (elements.dbTableSelect) {
    elements.dbTableSelect.addEventListener("change", async () => {
        dbState.offset = 0;
        dbState.selectedRow = null;
        await dbLoadColumns();
        await dbLoadRows();
    });
}
if (elements.dbFilterInput) {
    elements.dbFilterInput.addEventListener("input", (e) => {
        dbState.filter = e.target.value || "";
        renderDbTable();
    });
}
if (elements.dbPageSize) {
    elements.dbPageSize.addEventListener("change", (e) => {
        dbState.limit = Number(e.target.value || 50);
        dbState.offset = 0;
        dbLoadRows();
    });
}
if (elements.dbPrevBtn) {
    elements.dbPrevBtn.addEventListener("click", () => {
        dbState.offset = Math.max(0, dbState.offset - dbState.limit);
        dbLoadRows();
    });
}
if (elements.dbNextBtn) {
    elements.dbNextBtn.addEventListener("click", () => {
        dbState.offset = dbState.offset + dbState.limit;
        dbLoadRows();
    });
}

// Boot Sequence
initSystem();
ensureCallUuid();
connectWebSocket();
