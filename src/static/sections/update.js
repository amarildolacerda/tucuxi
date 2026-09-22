// src/static/sections/update.js
// Update card logic for settings page

const UPDATE_CHECK_INTERVAL = 2000; // 2s poll during update

let _updateState = {
    currentVersion: null,
    latestVersion: null,
    available: false,
    updating: false,
};

export function initUpdate() {
    checkForUpdate();
    _bindEvents();
}

function _bindEvents() {
    const btnCheck = document.getElementById("btn-check-update");
    const btnApply = document.getElementById("btn-apply-update");

    if (btnCheck) {
        btnCheck.addEventListener("click", () => checkForUpdate());
    }
    if (btnApply) {
        btnApply.addEventListener("click", () => applyUpdate());
    }
}

async function checkForUpdate() {
    const statusEl = document.getElementById("update-status");
    const actionsEl = document.getElementById("update-actions");

    statusEl.innerHTML = '<p style="color:var(--muted-subtle);">Verificando atualizações...</p>';

    try {
        const resp = await fetch("/api/system/update-check");
        if (!resp.ok) throw new Error("Falha ao checar atualizações");
        const data = await resp.json();

        _updateState.currentVersion = data.current_version;
        _updateState.latestVersion = data.latest_version;
        _updateState.available = data.update_available;

        if (data.update_available) {
            statusEl.innerHTML = `
                <p>Versão atual: <strong>${data.current_version}</strong></p>
                <p>Disponível: <strong style="color:var(--warning);">${data.latest_version}</strong></p>
            `;
            const btnApply = document.getElementById("btn-apply-update");
            btnApply.style.display = "inline-block";
            btnApply.textContent = `Atualizar para ${data.latest_version}`;
        } else {
            statusEl.innerHTML = `
                <p>Versão atual: <strong>${data.current_version}</strong></p>
                <p style="color:var(--success);">Sistema atualizado</p>
            `;
        }

        actionsEl.style.display = "block";

    } catch (e) {
        statusEl.innerHTML = `<p style="color:var(--error);">Erro: ${e.message}</p>`;
        actionsEl.style.display = "block";
    }
}

async function applyUpdate() {
    const tag = _updateState.latestVersion
        ? `v${_updateState.latestVersion}`
        : null;

    if (!tag) return;

    const progressEl = document.getElementById("update-progress");
    const progressText = document.getElementById("update-progress-text");
    const logEl = document.getElementById("update-log");
    const actionsEl = document.getElementById("update-actions");
    const resultEl = document.getElementById("update-result");

    actionsEl.style.display = "none";
    progressEl.style.display = "block";
    progressText.textContent = "Atualizando... Não desligue o Pi.";
    logEl.textContent = "";

    try {
        const resp = await fetch("/api/system/update", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ tag }),
        });
        const data = await resp.json();

        progressEl.style.display = "none";
        resultEl.style.display = "block";

        if (data.success) {
            resultEl.innerHTML = `
                <p style="color:var(--success);"><strong>Atualizado com sucesso! Reiniciando...</strong></p>
            `;
            setTimeout(() => location.reload(), 10000);
        } else {
            resultEl.innerHTML = `
                <p style="color:var(--error);"><strong>Falha ao atualizar</strong></p>
                <pre style="background:var(--surface-2);padding:0.5rem;border-radius:var(--radius-sm);font-size:0.8rem;max-height:200px;overflow-y:auto;">${(data.log || []).join("\n")}</pre>
                <button class="button-secondary button-mini" onclick="location.reload()" style="margin-top:8px;">Tentar novamente</button>
            `;
        }
    } catch (e) {
        progressEl.style.display = "none";
        resultEl.style.display = "block";
        resultEl.innerHTML = `
            <p style="color:var(--error);"><strong>Erro: ${e.message}</strong></p>
            <button class="button-secondary button-mini" onclick="location.reload()" style="margin-top:8px;">Tentar novamente</button>
        `;
    }
}

// Auto-init if loaded directly
if (document.getElementById("update-status")) {
    initUpdate();
}
