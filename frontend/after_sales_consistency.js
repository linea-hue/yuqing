(function () {
  const text = {
    label: "\u9644\u4ef6\u5185\u5bb9\u8bf4\u660e / OCR \u6458\u8981",
    placeholder: "\u8bf7\u8bf4\u660e\u9644\u4ef6\u4e2d\u5bf9\u5e94\u7684\u5546\u54c1\u3001\u95ee\u9898\u548c\u8ba2\u5355\u4fe1\u606f",
    required: "\u9009\u62e9\u4e86\u9644\u4ef6\u540e\uff0c\u8bf7\u586b\u5199\u9644\u4ef6\u5185\u5bb9\u8bf4\u660e\uff0c\u7528\u4e8e\u4e00\u81f4\u6027\u6821\u9a8c",
    checked: "\u9644\u4ef6\u4e00\u81f4\u6027\u6821\u9a8c",
  };

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[ch]));
  }

  function enhanceBuyer() {
    const form = document.getElementById("afterForm");
    const file = document.getElementById("afterEvidenceFile");
    if (!form || !file || document.getElementById("afterEvidenceDescription")) return;
    const label = document.createElement("label");
    label.className = "form-label";
    label.textContent = text.label;
    const description = document.createElement("textarea");
    description.className = "field";
    description.id = "afterEvidenceDescription";
    description.rows = 3;
    description.maxLength = 1000;
    description.placeholder = text.placeholder;
    file.insertAdjacentElement("afterend", label);
    label.insertAdjacentElement("afterend", description);

    form.onsubmit = async (event) => {
      event.preventDefault();
      const selected = file.files?.[0];
      const evidenceDescription = description.value.trim();
      if (selected && !evidenceDescription) {
        document.getElementById("afterResult").innerHTML = `<div class="notice err">${esc(text.required)}</div>`;
        return;
      }
      try {
        const created = await window.api("/api/after-sales", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Idempotency-Key": crypto.randomUUID() },
          body: JSON.stringify({
            order_id: document.getElementById("afterOrder").value,
            amount: Number(document.getElementById("afterAmount").value),
            reason: document.getElementById("afterReason").value,
            evidence_confidence: Number(document.getElementById("evidence").value),
            service_type: document.getElementById("afterType").value,
            evidence_filename: selected?.name || null,
            evidence_description: evidenceDescription || null,
          }),
        });
        let consistency = created.evidence_consistency;
        if (selected) {
          const body = new FormData();
          body.append("file", selected);
          body.append("evidence_text", evidenceDescription);
          const uploaded = await window.api(`/api/after-sales/${encodeURIComponent(created.id)}/evidence`, { method: "POST", body });
          consistency = uploaded.consistency;
        }
        const result = document.getElementById("afterResult");
        result.innerHTML = `<div class="notice ${consistency?.status === "mismatch" ? "err" : "ok"}">${esc(text.checked)}：${esc(consistency?.status || "missing")}，${esc(consistency?.reason || created.decision_reason || "")}</div>`;
        if (typeof window.loadCases === "function") await window.loadCases();
        if (typeof window.loadOrders === "function") await window.loadOrders();
      } catch (error) {
        document.getElementById("afterResult").innerHTML = `<div class="notice err">${esc(error.message)}`;
      }
    };
  }

  function enhanceOps() {
    if (!document.getElementById("caseDetailBody") || typeof window.showCase !== "function") return;
    const original = window.showCase;
    window.showCase = async function (id) {
      await original(id);
      try {
        const current = await fetch(`/api/after-sales/${encodeURIComponent(id)}`).then((response) => response.json());
        const summary = current.evidence_consistency;
        if (!summary) return;
        const body = document.getElementById("caseDetailBody");
        const marker = document.createElement("p");
        marker.innerHTML = `<b>${esc(text.checked)}：</b><span class="tag ${summary.status === "matched" ? "ok" : summary.status === "mismatch" ? "red" : "warn"}">${esc(summary.status)}</span> ${esc(summary.reason)}`;
        body.querySelector(".detail .card")?.appendChild(marker);
      } catch (_) {}
    };
  }

  function enhanceKnowledgePreview() {
    const docs = document.getElementById("opsDocs");
    const upload = document.getElementById("kbUpload");
    const result = document.getElementById("kbUploadResult");
    if (!docs || !upload || !result) return;

    async function renderPreview() {
      try {
        const response = await fetch("/api/knowledge/documents");
        const data = await response.json();
        const rows = docs.querySelectorAll("table tr");
        rows.forEach((row, index) => {
          if (index === 0 || row.querySelector(".doc-preview")) return;
          const id = row.querySelector("td:nth-child(1) .muted")?.textContent?.trim();
          const item = data.items.find((entry) => entry.id === id);
          const cell = document.createElement("td");
          cell.className = "doc-preview";
          cell.textContent = item?.preview || "\u6682\u65e0\u53ef\u7528\u5185\u5bb9";
          row.appendChild(cell);
        });
        const header = docs.querySelector("table tr");
        if (header && !header.querySelector(".preview-header")) {
          const cell = document.createElement("th");
          cell.className = "preview-header";
          cell.textContent = "\u5185\u5bb9\u9884\u89c8";
          header.appendChild(cell);
        }
      } catch (_) {}
    }

    const observer = new MutationObserver(renderPreview);
    observer.observe(docs, { childList: true, subtree: true });
    upload.addEventListener("click", () => {
      window.setTimeout(async () => {
        await renderPreview();
        const latest = docs.querySelector("table tr:nth-child(2) .doc-preview");
        if (latest?.textContent) result.textContent += `\uff1b\u5185\u5bb9\u9884\u89c8\uff1a${latest.textContent.slice(0, 180)}`;
      }, 450);
    });
    renderPreview();
  }

  function enhanceBatchApproval() {
    const section = document.getElementById("batch");
    const file = section?.querySelector('input[type="file"]');
    const upload = file?.nextElementSibling;
    if (!section || !file || !upload) return;
    if (!document.getElementById("batchDemoXlsx")) {
      const demo = document.createElement("button");
      demo.id = "batchDemoXlsx";
      demo.className = "btn light";
      demo.type = "button";
      demo.textContent = "\u4e0b\u8f7d\u901a\u8fc7\u6d4b\u8bd5\u8868";
      demo.style.marginLeft = "8px";
      upload.insertAdjacentElement("afterend", demo);
      demo.onclick = async () => {
        const session = JSON.parse(localStorage.getItem("ops_session") || "null");
        const response = await fetch("/api/ops/batch/export-test-xlsx", {
          headers: { Authorization: `Bearer ${session?.token || ""}` },
        });
        if (!response.ok) {
          alert("\u4e0b\u8f7d\u5931\u8d25\uff0c\u8bf7\u91cd\u65b0\u767b\u5f55\u540e\u518d\u8bd5");
          return;
        }
        const blob = await response.blob();
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = "suspended-approve-demo.xlsx";
        link.click();
        URL.revokeObjectURL(link.href);
      };
    }

    upload.onclick = async () => {
      const result = document.getElementById("batchUploadResult") || (() => {
        const element = document.createElement("div");
        element.id = "batchUploadResult";
        element.className = "notice";
        upload.insertAdjacentElement("afterend", element);
        return element;
      })();
      const selected = file.files?.[0];
      if (!selected) {
        result.textContent = "\u8bf7\u5148\u9009\u62e9 CSV \u6216 XLSX \u6587\u4ef6";
        return;
      }
      try {
        const body = new FormData();
        body.append("file", selected);
        const session = JSON.parse(localStorage.getItem("ops_session") || "null");
        const response = await fetch("/api/ops/batch/import", {
          method: "POST",
          headers: { Authorization: `Bearer ${session?.token || ""}` },
          body,
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "\u6279\u91cf\u5ba1\u6279\u5931\u8d25");
        result.textContent = `\u6279\u5904\u7406\u5b8c\u6210\uff1a\u8bfb\u53d6 ${data.parsed_rows} \u884c\uff0c\u6279\u51c6 ${data.approved} \u6761\uff0c\u62d2\u7edd ${data.rejected} \u6761\uff0c\u5931\u8d25 ${data.failed} \u6761\uff0c\u8df3\u8fc7 ${data.skipped} \u6761\u3002`;
        const cards = section.querySelectorAll(".card");
        const metrics = cards[1]?.querySelectorAll(".metric");
        if (metrics?.length >= 3) {
          metrics[0].textContent = data.approved;
          metrics[1].textContent = data.rejected;
          metrics[2].textContent = data.failed;
        }
        const detail = document.createElement("div");
        detail.className = "small";
        detail.innerHTML = data.details.map((item) => `${esc(item.ticket_no || "-")}：${esc(item.status)}${item.reason ? ` · ${esc(item.reason)}` : ""}`).join("<br>");
        result.insertAdjacentElement("afterend", detail);
        if (typeof window.loadBatch === "function") window.loadBatch();
        if (typeof window.loadWork === "function") window.loadWork();
      } catch (error) {
        result.textContent = `\u6587\u4ef6\u5904\u7406\u5931\u8d25\uff1a${error.message}`;
      }
    };
  }

  window.addEventListener("load", () => {
    enhanceBuyer();
    enhanceOps();
    enhanceKnowledgePreview();
    enhanceBatchApproval();
  });
})();
