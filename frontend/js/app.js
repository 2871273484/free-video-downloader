// ===== 下崽儿前端逻辑 =====
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

const state = {
  token: localStorage.getItem("member_token") || "",
  member: false,
  aiEnabled: false,
  parsed: null,
  selectedQuality: null,
  polling: {},
};

// ---------- 工具 ----------
function toast(msg, ms = 2600) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(t._t);
  t._t = setTimeout(() => t.classList.remove("show"), ms);
}

function headers(extra = {}) {
  const h = { "Content-Type": "application/json", ...extra };
  if (state.token) h["X-Member"] = state.token;
  return h;
}

async function api(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "请求失败");
  return data;
}

function qualityTag(q) {
  if (q === "audio") return "MP3";
  if (q === "nowm") return "无水印";
  if (/^dy_(\d+)$/.test(q)) return q.replace(/^dy_/, "") + "P 无水印";
  if (/^\d+$/.test(q)) return q + "P";
  if (q === "best") return "最佳";
  return q;
}

function fmtDuration(sec) {
  if (!sec) return "";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

// ---------- 会员态 ----------
async function refreshMe() {
  try {
    const me = await (await fetch("/api/me", { headers: headers() })).json();
    state.member = me.member;
    state.aiEnabled = me.ai_enabled;
    $("#memberPill").classList.toggle("hidden", !me.member);
  } catch (_) {}
}

// ---------- 解析 ----------
async function doParse(url) {
  if (!url || !/^https?:\/\//i.test(url)) {
    toast("先粘个正经链接呗～");
    return;
  }
  const btn = $("#parseBtn");
  const old = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<iconify-icon icon="solar:refresh-bold" class="spin"></iconify-icon><span>解析中</span>';
  try {
    const info = await api("/api/parse", { url });
    state.parsed = info;
    renderResult(info);
  } catch (e) {
    toast(e.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = old;
  }
}

function renderResult(info) {
  $("#rThumb").src = info.thumbnail || "https://picsum.photos/seed/dl/640/360";
  $("#rTitle").textContent = info.title;
  $("#rUploader").innerHTML = info.uploader
    ? `<iconify-icon icon="solar:user-bold"></iconify-icon>${info.uploader}`
    : "";
  $("#rDuration").innerHTML = info.duration
    ? `<iconify-icon icon="solar:clock-circle-bold"></iconify-icon>${fmtDuration(info.duration)}`
    : "";
  $("#rExtractor").textContent = info.extractor || "";

  const row = $("#qualityRow");
  row.innerHTML = "";
  state.selectedQuality = null;
  const qualities = info.qualities.length
    ? info.qualities
    : [{ id: "best", label: "最佳画质", size: null }];
  qualities.forEach((q, i) => {
    const chip = document.createElement("button");
    chip.className = "chip";
    const locked = !state.member && q.height && q.height > 720;
    chip.innerHTML = `${q.label}${q.size ? `<span class="sz">${q.size}</span>` : ""}${
      locked ? ' <iconify-icon icon="solar:lock-keyhole-bold"></iconify-icon>' : ""
    }`;
    chip.onclick = () => {
      $$("#qualityRow .chip").forEach((c) => c.classList.remove("active"));
      chip.classList.add("active");
      state.selectedQuality = q.id;
      state.selectedLabel = q.label;
      state.selectedLocked = locked;
      updateDownloadBtn();
    };
    row.appendChild(chip);
    if (i === 0 || (q.height && q.height === 720)) {
      chip.click();
    }
  });
  if (!state.selectedQuality && qualities[0]) {
    row.firstChild.click();
  }

  $("#resultSection").classList.remove("hidden");
  $("#resultSection").scrollIntoView({ behavior: "smooth", block: "start" });
}

function updateDownloadBtn() {
  const btn = $("#downloadBtn");
  if (!btn) return;
  const q = state.selectedLabel || "";
  if (state.selectedLocked) {
    btn.innerHTML =
      '<iconify-icon icon="solar:lock-keyhole-bold"></iconify-icon> 开会员下 ' + q;
  } else {
    btn.innerHTML =
      '<iconify-icon icon="solar:download-minimalistic-bold"></iconify-icon> 开下！' +
      (q ? "· " + q : "");
  }
}

// ---------- 下载 ----------
async function startDownload(url, quality, title) {
  try {
    const { job_id } = await api("/api/download", { url, quality, title });
    addTask(job_id, title || url, quality);
  } catch (e) {
    handlePaywall(e);
  }
}

function handlePaywall(e) {
  toast(e.message);
  if (/会员|会員|开会员|402/.test(e.message)) {
    setTimeout(() => openRedeem(), 900);
  }
}

// ---------- 任务卡片 ----------
function addTask(jobId, title, quality) {
  $("#taskSection").classList.remove("hidden");
  const list = $("#taskList");
  const card = document.createElement("div");
  card.className = "slab p-4 reveal";
  card.id = "task-" + jobId;
  card.innerHTML = `
    <div class="flex items-start gap-2 mb-3">
      <iconify-icon icon="solar:videocamera-record-bold" style="font-size:22px;color:#1777ff"></iconify-icon>
      <div class="font-bold text-sm leading-snug flex-1" style="word-break:break-all">${title}</div>
      <span class="text-xs tape">${qualityTag(quality)}</span>
    </div>
    <div class="bar"><i></i></div>
    <div class="flex items-center justify-between mt-2 text-xs" style="color:#7a7364">
      <span class="st">排队中…</span>
      <span class="sp"></span>
    </div>
    <div class="act mt-3 hidden"></div>`;
  list.prepend(card);
  pollTask(jobId);
}

function pollTask(jobId) {
  const card = $("#task-" + jobId);
  const bar = card.querySelector(".bar");
  const fill = card.querySelector(".bar > i");
  const st = card.querySelector(".st");
  const sp = card.querySelector(".sp");
  const act = card.querySelector(".act");

  const tick = async () => {
    try {
      const p = await (await fetch("/api/progress/" + jobId, { headers: headers() })).json();
      fill.style.width = (p.progress || 0) + "%";
      sp.textContent = p.speed || "";
      if (p.status === "downloading") st.textContent = `下载中 ${p.progress}%`;
      else if (p.status === "processing") st.textContent = "合并处理中…";
      else if (p.status === "queued") st.textContent = "排队中…";
      else if (p.status === "done") {
        bar.classList.add("done");
        st.textContent = "搞定！";
        sp.textContent = "";
        act.classList.remove("hidden");
        act.innerHTML = `<a class="btn btn-blue w-full justify-center" href="/api/file/${jobId}" download>
          <iconify-icon icon="solar:download-minimalistic-bold"></iconify-icon> 保存到设备</a>`;
        return;
      } else if (p.status === "error") {
        bar.classList.add("error");
        st.textContent = "翻车了：" + (p.error || "未知错误");
        return;
      }
      setTimeout(tick, 1000);
    } catch (e) {
      st.textContent = "任务丢失了";
    }
  };
  tick();
}

// ---------- AI ----------
async function runAI(kind) {
  if (!state.parsed) return;
  if (!state.aiEnabled) {
    toast("AI 还没配置，去 .env 填 Key 就能用啦");
    return;
  }
  const sec = $("#aiSection");
  const body = $("#aiBody");
  $("#aiTitle").textContent = kind === "sum" ? "AI 总结" : "字幕翻译";
  body.textContent = "AI 正在看视频…（抓字幕 + 思考，稍等）";
  sec.classList.remove("hidden");
  sec.scrollIntoView({ behavior: "smooth", block: "start" });
  try {
    const path = kind === "sum" ? "/api/summarize" : "/api/translate";
    const data = await api(path, {
      url: state.parsed.webpage_url,
      title: state.parsed.title,
      target_lang: "中文",
    });
    body.textContent = data.summary || data.translation || "没有内容";
  } catch (e) {
    body.textContent = "";
    handlePaywall(e);
  }
}

// ---------- 兑换码 ----------
function openRedeem() {
  $("#redeemModal").classList.add("show");
}
function closeRedeem() {
  $("#redeemModal").classList.remove("show");
}
async function doRedeem(code) {
  if (!code) return toast("先输入兑换码");
  try {
    const data = await api("/api/redeem", { code });
    state.token = data.token;
    localStorage.setItem("member_token", data.token);
    await refreshMe();
    closeRedeem();
    toast("🎉 会员已激活，去下 4K 吧！");
    if (state.parsed) renderResult(state.parsed);
  } catch (e) {
    toast(e.message);
  }
}

// ---------- 事件绑定 ----------
function bind() {
  $("#parseBtn").onclick = () => doParse($("#urlInput").value.trim());
  $("#urlInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") doParse($("#urlInput").value.trim());
  });

  $("#batchToggle").onclick = () => {
    $("#batchInput").classList.toggle("hidden");
    $("#batchActions").classList.toggle("hidden");
  };
  $("#batchGo").onclick = async () => {
    const urls = $("#batchInput").value.split("\n").map((s) => s.trim()).filter(Boolean);
    if (!urls.length) return toast("一行一个链接哦");
    const quality = state.member ? "1080" : "720";
    try {
      const { jobs } = await api("/api/batch", { urls, quality });
      jobs.forEach((j) => addTask(j.job_id, j.url, quality));
      toast(`已开下 ${jobs.length} 个`);
    } catch (e) {
      handlePaywall(e);
    }
  };

  $("#downloadBtn").onclick = () =>
    startDownload(state.parsed.webpage_url, state.selectedQuality || "720", state.parsed.title);
  $("#audioBtn").onclick = () =>
    startDownload(state.parsed.webpage_url, "audio", state.parsed.title);
  $("#sumBtn").onclick = () => runAI("sum");
  $("#transBtn").onclick = () => runAI("trans");

  $("#openRedeem").onclick = openRedeem;
  $("#closeRedeem").onclick = closeRedeem;
  $("#redeemModal").onclick = (e) => {
    if (e.target.id === "redeemModal") closeRedeem();
  };
  $("#redeemBtn").onclick = () => doRedeem($("#redeemInput").value.trim());
  $("#redeemInlineBtn").onclick = () => doRedeem($("#redeemInline").value.trim());
}

bind();
refreshMe();
