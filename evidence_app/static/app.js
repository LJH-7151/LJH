(() => {
  "use strict";

  const MAX_FILE_SIZE = 2 * 1024 * 1024;
  const elements = {
    serviceStatus: document.querySelector("#service-status"),
    uploadForm: document.querySelector("#upload-form"),
    fileInput: document.querySelector("#file-input"),
    uploadButton: document.querySelector("#upload-button"),
    refreshButton: document.querySelector("#refresh-button"),
    notice: document.querySelector("#notice"),
    count: document.querySelector("#document-count"),
    libraryStatus: document.querySelector("#library-status"),
    documentList: document.querySelector("#document-list"),
    detailPanel: document.querySelector("#detail-panel"),
    detailStatus: document.querySelector("#detail-status"),
    detailContent: document.querySelector("#detail-content"),
    downloadLink: document.querySelector("#download-link"),
    title: document.querySelector("#document-title"),
    filename: document.querySelector("#document-filename"),
    time: document.querySelector("#document-time"),
    size: document.querySelector("#document-size"),
    chunkCount: document.querySelector("#document-chunk-count"),
    hash: document.querySelector("#document-hash"),
    chunkList: document.querySelector("#chunk-list")
  };
  const localToken = document.querySelector('meta[name="local-token"]').content;
  let documents = [];
  let selectedId = null;
  let detailRequest = 0;
  let uploading = false;
  let refreshing = false;

  function createElement(tagName, className, text) {
    const element = document.createElement(tagName);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = String(text);
    return element;
  }

  function showNotice(message, kind = "success") {
    elements.notice.textContent = message;
    elements.notice.className = `notice notice-${kind}`;
    elements.notice.setAttribute("role", kind === "error" ? "alert" : "status");
    elements.notice.hidden = false;
  }

  function updateBusyState() {
    elements.fileInput.disabled = uploading;
    elements.uploadButton.disabled = uploading || refreshing;
    elements.uploadButton.textContent = uploading ? "正在导入…" : "导入资料";
    elements.refreshButton.disabled = refreshing || uploading;
    elements.refreshButton.textContent = refreshing ? "读取中…" : "刷新";
    elements.uploadForm.setAttribute("aria-busy", String(uploading));
  }

  async function requestJson(url, options = {}) {
    let response;
    try {
      response = await fetch(url, { credentials: "same-origin", ...options });
    } catch {
      throw new Error("无法连接本地服务，请确认服务已启动后重试。");
    }
    let payload;
    try {
      payload = await response.json();
    } catch {
      throw new Error("服务返回了无法识别的内容，请刷新后重试。");
    }
    if (!response.ok) {
      throw new Error(typeof payload.error === "string" ? payload.error : "请求未完成，请稍后重试。");
    }
    return payload;
  }

  function formatSize(size) {
    if (size < 1024) return `${size} B`;
    if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KiB`;
    return `${(size / (1024 * 1024)).toFixed(2)} MiB`;
  }

  function formatTime(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat("zh-CN", {
      year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit"
    }).format(date);
  }

  function renderDocuments() {
    elements.documentList.replaceChildren();
    elements.count.textContent = String(documents.length);
    documents.forEach((item) => {
      const row = createElement("li");
      const button = createElement("button", "document-item");
      button.type = "button";
      button.setAttribute("aria-pressed", String(item.id === selectedId));
      button.append(
        createElement("span", "document-item-title", item.title || item.filename),
        createElement("span", "document-item-filename", item.filename),
        createElement("span", "document-item-meta", `${item.chunk_count} 段原文 · ${formatSize(item.size)}`)
      );
      button.addEventListener("click", () => selectDocument(item.id));
      row.append(button);
      elements.documentList.append(row);
    });
    elements.libraryStatus.hidden = documents.length > 0;
    if (documents.length === 0) {
      elements.libraryStatus.textContent = "还没有资料。导入第一份文本，开始保留出处。";
    }
  }

  async function selectDocument(id) {
    selectedId = id;
    renderDocuments();
    const requestNumber = ++detailRequest;
    elements.detailPanel.setAttribute("aria-busy", "true");
    elements.detailContent.hidden = true;
    elements.downloadLink.hidden = true;
    elements.detailStatus.hidden = false;
    elements.detailStatus.textContent = "正在读取来源与原文…";
    try {
      const result = await requestJson(`/api/document-text?id=${encodeURIComponent(id)}`);
      if (requestNumber !== detailRequest) return;
      renderDetail(result.document, result.chunks);
    } catch (error) {
      if (requestNumber !== detailRequest) return;
      elements.detailStatus.textContent = error.message;
    } finally {
      if (requestNumber === detailRequest) elements.detailPanel.setAttribute("aria-busy", "false");
    }
  }

  function renderDetail(item, chunks) {
    elements.title.textContent = item.title || item.filename;
    elements.filename.textContent = item.filename;
    elements.time.textContent = formatTime(item.created_at);
    elements.size.textContent = formatSize(item.size);
    elements.chunkCount.textContent = String(item.chunk_count);
    elements.hash.textContent = item.sha256;
    elements.downloadLink.href = `/api/original?id=${encodeURIComponent(item.id)}`;
    elements.downloadLink.setAttribute("download", item.filename);
    elements.downloadLink.hidden = false;
    elements.chunkList.replaceChildren();
    chunks.forEach((chunk, index) => {
      const article = createElement("article", "source-chunk");
      const heading = createElement("div", "chunk-heading");
      heading.append(
        createElement("h4", "", `第 ${index + 1} 段`),
        createElement("span", "line-range", `原文第 ${chunk.start_line}–${chunk.end_line} 行`)
      );
      article.append(heading);
      if (chunk.location) article.append(createElement("p", "chunk-location", chunk.location));
      article.append(createElement("pre", "source-text", chunk.content));
      elements.chunkList.append(article);
    });
    if (chunks.length === 0) {
      elements.chunkList.append(createElement("p", "empty-state", "这份资料没有可展示的文本段。"));
    }
    elements.detailStatus.hidden = true;
    elements.detailContent.hidden = false;
  }

  async function refreshDocuments(preferredId = null) {
    if (refreshing) return false;
    refreshing = true;
    updateBusyState();
    try {
      const result = await requestJson("/api/documents");
      documents = result.documents;
      const nextId = preferredId || selectedId;
      const selection = documents.find((item) => item.id === nextId) || documents[0];
      selectedId = selection ? selection.id : null;
      renderDocuments();
      if (selection) {
        await selectDocument(selection.id);
      } else {
        ++detailRequest;
        elements.detailPanel.setAttribute("aria-busy", "false");
        elements.detailStatus.textContent = "选择一份资料，查看来源与原文。";
        elements.detailStatus.hidden = false;
        elements.detailContent.hidden = true;
        elements.downloadLink.hidden = true;
      }
      return true;
    } catch (error) {
      if (documents.length === 0) {
        elements.libraryStatus.hidden = false;
        elements.libraryStatus.textContent = "暂时无法读取资料，请点击刷新重试。";
      }
      showNotice(error.message, "error");
      return false;
    } finally {
      refreshing = false;
      updateBusyState();
    }
  }

  function toBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    const parts = [];
    const step = 8192;
    for (let offset = 0; offset < bytes.length; offset += step) {
      parts.push(String.fromCharCode(...bytes.subarray(offset, offset + step)));
    }
    return btoa(parts.join(""));
  }

  elements.uploadForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (uploading || refreshing) return;
    const file = elements.fileInput.files[0];
    if (!file) {
      showNotice("请先选择一份 TXT 或 Markdown 文件。", "error");
      return;
    }
    if (!/\.(txt|md)$/i.test(file.name)) {
      showNotice("请选择 .txt 或 .md 文件。", "error");
      return;
    }
    if (file.size === 0 || file.size > MAX_FILE_SIZE) {
      showNotice(file.size === 0 ? "文件为空，请选择包含文字的文件。" : "文件超过 2 MiB，请选择较小的文件。", "error");
      return;
    }
    uploading = true;
    updateBusyState();
    showNotice("正在导入资料…", "info");
    try {
      const buffer = await file.arrayBuffer();
      try {
        new TextDecoder("utf-8", { fatal: true }).decode(buffer);
      } catch {
        throw new Error("文件不是有效的 UTF-8 文本，请转换编码后重试。");
      }
      const result = await requestJson("/api/upload", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Local-Token": localToken },
        body: JSON.stringify({ name: file.name, content: toBase64(buffer) })
      });
      elements.fileInput.value = "";
      const refreshed = await refreshDocuments(result.document.id);
      if (refreshed) {
        showNotice(result.duplicate ? "这份原件已在资料库中，已打开已有记录。" : "资料已导入，可查看原文与行号。");
      } else {
        showNotice("资料已保存，但资料库刷新失败，请点击刷新重试。", "error");
      }
    } catch (error) {
      showNotice(error.message || "文件读取失败，请重新选择后重试。", "error");
    } finally {
      uploading = false;
      updateBusyState();
    }
  });

  elements.refreshButton.addEventListener("click", () => refreshDocuments());
  elements.fileInput.addEventListener("change", () => { elements.notice.hidden = true; });

  async function checkHealth() {
    try {
      const result = await requestJson("/api/health");
      if (result.status !== "ok") throw new Error("服务状态异常");
      elements.serviceStatus.textContent = "本地服务已连接";
      elements.serviceStatus.classList.add("connected");
    } catch {
      elements.serviceStatus.textContent = "本地服务未连接";
      elements.serviceStatus.classList.add("disconnected");
    }
  }

  Promise.allSettled([checkHealth(), refreshDocuments()]);
})();
