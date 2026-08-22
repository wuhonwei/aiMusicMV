async function api(path, options = {}) {
  const opts = {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  };
  const res = await fetch(path, opts);
  let data = null;
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) {
    data = await res.json();
  } else {
    data = await res.text();
  }
  if (!res.ok) {
    const msg =
      (data && data.detail && (data.detail.message || JSON.stringify(data.detail))) ||
      (typeof data === "string" ? data : JSON.stringify(data));
    const err = new Error(msg || `HTTP ${res.status}`);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

function showToast(text, isError) {
  let el = document.getElementById("toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "toast";
    el.className = "toast";
    document.body.appendChild(el);
  }
  el.textContent = text;
  el.style.borderColor = isError ? "#e06c75" : "#3db8a0";
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 4500);
}

async function runAction(btn, url, { reload = true, method = "POST", body = null } = {}) {
  if (btn) btn.disabled = true;
  try {
    await api(url, {
      method,
      body: body ? JSON.stringify(body) : undefined,
    });
    showToast("完成");
    if (reload) location.reload();
  } catch (e) {
    showToast(e.message || String(e), true);
    if (btn) btn.disabled = false;
    if (e.status === 409) {
      // keep page
    } else if (reload) {
      // still refresh to show failed state
      setTimeout(() => location.reload(), 800);
    }
  }
}

function collectCreativeFromForm() {
  const root = document.getElementById("creative-editor");
  if (!root) return null;
  const data = JSON.parse(root.dataset.base);
  data.title = document.getElementById("c-title").value;
  data.language = document.getElementById("c-language").value;
  data.music_description = document.getElementById("c-music-desc").value;
  data.performance_notes = document.getElementById("c-perf").value;
  data.visual_bible.setting = document.getElementById("vb-setting").value;
  data.visual_bible.palette = document.getElementById("vb-palette").value;
  data.visual_bible.character = document.getElementById("vb-character").value;
  data.visual_bible.camera_style = document.getElementById("vb-camera").value;

  const sections = [];
  root.querySelectorAll("[data-section]").forEach((el) => {
    const idx = el.dataset.section;
    sections.push({
      id: el.querySelector(".s-id").value,
      label: el.querySelector(".s-label").value,
      lyrics: el.querySelector(".s-lyrics").value,
      visual_prompt: el.querySelector(".s-visual").value,
      negative_prompt: el.querySelector(".s-neg").value,
      shot_count: parseInt(el.querySelector(".s-shots").value || "1", 10),
    });
  });
  data.sections = sections;
  return data;
}

async function saveCreative(btn) {
  const creative = collectCreativeFromForm();
  if (!creative) return;
  const pid = document.body.dataset.projectId;
  await runAction(btn, `/api/projects/${pid}/creative`, {
    method: "PUT",
    body: { creative },
    reload: true,
  });
}
