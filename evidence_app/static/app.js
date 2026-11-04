(() => {
  "use strict";

  const MAX_FILE_SIZE = 2 * 1024 * 1024;
  const elements = {
    serviceStatus: document.querySelector("#service-status"),
    uploadForm: document.querySelector("#upload-form"),
    fileInput: document.querySelector("#file-input"),
    uploadButton: document.querySelector("#upload-button"),
    searchPanel: document.querySelector("#search-panel"),
    searchForm: document.querySelector("#search-form"),
    searchQuery: document.querySelector("#search-query"),
    searchDocument: document.querySelector("#search-document"),
    searchButton: document.querySelector("#search-button"),
    clearSearchButton: document.querySelector("#clear-search-button"),
    searchStatus: document.querySelector("#search-status"),
    searchResults: document.querySelector("#search-results"),
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
  let searchRequest = 0;
  let searchController = null;
  let searching = false;
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
    elements.searchQuery.disabled = uploading || refreshing;
    elements.searchDocument.disabled = uploading || refreshing;
    elements.searchButton.disabled = uploading || refreshing;
    elements.searchButton.textContent = searching ? "检索中…" : "检索";
    elements.searchPanel.setAttribute("aria-busy", String(searching));
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

  function syncSearchDocuments() {
    const previousId = elements.searchDocument.value;
    const options = [createElement("option", "", "全部资料")];
    options[0].value = "";
    documents.forEach((item) => {
      const option = createElement("option", "", item.filename);
      option.value = item.id;
      options.push(option);
    });
    elements.searchDocument.replaceChildren(...options);
    elements.searchDocument.value = documents.some((item) => item.id === previousId) ? previousId : "";
  }

  function invalidateSearch(message = "输入关键词，查找本地资料中的原文段落。") {
    ++searchRequest;
    if (searchController) searchController.abort();
    searchController = null;
    searching = false;
    elements.searchResults.replaceChildren();
    elements.searchResults.hidden = true;
    elements.searchStatus.textContent = message;
    elements.searchStatus.setAttribute("role", "status");
    updateBusyState();
  }

  function renderSearchResults(result) {
    const count = result.results.length;
    elements.searchStatus.textContent = result.total === 0
      ? "没有找到匹配段落。请调整关键词或资料范围。"
      : `共找到 ${result.total} 段匹配原文。${result.has_more ? `当前显示前 ${count} 条；每次最多显示 20 条，请缩小范围查看更多。` : `已显示全部 ${count} 条。`}`;
    elements.searchResults.replaceChildren();
    result.results.forEach((item) => {
      const row = createElement("li", "search-result");
      const heading = createElement("div", "result-heading");
      const title = createElement("h3", "", item.title || item.filename);
      const openButton = createElement("button", "button button-quiet", "查看原文");
      openButton.type = "button";
      openButton.addEventListener("click", () => selectDocument(item.document_id, item.chunk_id));
      heading.append(title, openButton);
      const meta = createElement("p", "result-meta");
      meta.append(
        createElement("span", "result-filename", item.filename),
        createElement("span", "", `第 ${item.position} 段 · 原文第 ${item.start_line}–${item.end_line} 行`)
      );
      const fingerprint = createElement("details", "result-fingerprint");
      fingerprint.append(
        createElement("summary", "", `原件 SHA-256：${String(item.sha256).slice(0, 12)}…（展开查看）`),
        createElement("code", "", item.sha256)
      );
      row.append(heading, meta, createElement("pre", "result-excerpt", item.excerpt), fingerprint);
      elements.searchResults.append(row);
    });
    elements.searchResults.hidden = count === 0;
  }

  async function searchDocuments(event) {
    event.preventDefault();
    if (uploading || refreshing) return;
    invalidateSearch();
    const query = elements.searchQuery.value.trim();
    const terms = query ? query.split(/\s+/u) : [];
    if (!query || Array.from(query).length > 200 || terms.length > 8) {
      elements.searchStatus.textContent = !query ? "请输入至少一个关键词。" : "检索内容最多 200 个字符、8 个关键词。";
      elements.searchStatus.setAttribute("role", "alert");
      elements.searchQuery.focus();
      return;
    }
    const requestNumber = searchRequest;
    searchController = new AbortController();
    searching = true;
    elements.searchStatus.textContent = "正在检索本地原文…";
    updateBusyState();
    const parameters = new URLSearchParams({ q: query, limit: "20" });
    if (elements.searchDocument.value) parameters.set("document_id", elements.searchDocument.value);
    try {
      const result = await requestJson(`/api/search?${parameters}`, { signal: searchController.signal });
      if (requestNumber !== searchRequest) return;
      renderSearchResults(result);
    } catch (error) {
      if (requestNumber !== searchRequest) return;
      elements.searchStatus.textContent = error.message;
      elements.searchStatus.setAttribute("role", "alert");
    } finally {
      if (requestNumber === searchRequest) {
        searchController = null;
        searching = false;
        updateBusyState();
      }
    }
  }

  async function selectDocument(id, chunkId = null) {
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
      if (chunkId) {
        const target = Array.from(elements.chunkList.children).find((element) => element.dataset.chunkId === chunkId);
        if (target) {
          target.classList.add("source-chunk-highlighted");
          target.focus({ preventScroll: true });
          target.scrollIntoView({ block: "center" });
        } else {
          showNotice("该来源段落已不可用，请刷新资料后重新检索。", "error");
        }
      }
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
      article.dataset.chunkId = chunk.id;
      article.tabIndex = -1;
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
    invalidateSearch("资料库正在刷新，完成后可重新检索。");
    updateBusyState();
    try {
      const result = await requestJson("/api/documents");
      documents = result.documents;
      syncSearchDocuments();
      invalidateSearch("资料库已刷新，输入关键词检索原文。");
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
    invalidateSearch("导入资料后，请重新检索以获取最新结果。");
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
  elements.searchForm.addEventListener("submit", searchDocuments);
  elements.searchQuery.addEventListener("input", () => invalidateSearch("关键词已修改，请重新检索。"));
  elements.searchDocument.addEventListener("change", () => invalidateSearch("资料范围已修改，请重新检索。"));
  elements.clearSearchButton.addEventListener("click", () => {
    elements.searchQuery.value = "";
    elements.searchDocument.value = "";
    invalidateSearch();
    elements.searchQuery.focus();
  });

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
