import AgoraRTC, {
  IAgoraRTCClient,
  ILocalAudioTrack,
  ILocalVideoTrack,
  IRemoteAudioTrack,
} from "agora-rtc-sdk-ng";

type Credentials = {
  app_id: string;
  channel: string;
  uid: number;
  token: string;
  expires_in: number;
  default_quality?: string;
};

class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly code = "") {
    super(message);
  }
}

const $ = <T extends HTMLElement>(id: string): T => document.getElementById(id) as T;
const presenterMode = location.pathname.includes("/screen-share/p/");
const presenterPage = location.pathname === "/screen-share/p" || presenterMode;
function linkToken(): string {
  const raw = location.hash.slice(1) || location.pathname.split("/").filter(Boolean).pop() || "";
  try { return decodeURIComponent(raw); } catch { return ""; }
}
const rawLinkToken = linkToken();

function viewerInstance(): string {
  const key = "oopz-screen-share-viewer-instance";
  try {
    const existing = sessionStorage.getItem(key);
    if (existing) return existing;
    const created = crypto.randomUUID();
    sessionStorage.setItem(key, created);
    return created;
  } catch {
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
  }
}

const viewerInstanceId = presenterPage ? "" : viewerInstance();
const statusEl = $("status");
const detailEl = $("detail");
const startButton = $("start") as HTMLButtonElement;
const stopButton = $("stop") as HTMLButtonElement;
const playButton = $("play-audio") as HTMLButtonElement;
const fullscreenButton = $("fullscreen") as HTMLButtonElement;
const qualitySelect = $("quality") as HTMLSelectElement;
const frameRateSelect = $("frame-rate") as HTMLSelectElement;
const stage = $("stage");
const controlPanel = $("control-panel");
const panelBar = $("panel-bar");
const outputProfile = $("output-profile");
const viewerControls = $("viewer-controls");

let client: IAgoraRTCClient | null = null;
let screenVideo: ILocalVideoTrack | null = null;
let screenAudio: ILocalAudioTrack | null = null;
let heartbeatTimer = 0;
let heartbeatFailures = 0;
let stopping = false;
let tokenRenewTimer = 0;
let tokenRenewing = false;
let tokenRenewFailures = 0;
const remoteAudioTracks = new Set<IRemoteAudioTrack>();

function setStatus(title: string, detail = "", kind: "idle" | "ok" | "warn" | "error" = "idle") {
  statusEl.textContent = title;
  statusEl.dataset.kind = kind;
  detailEl.textContent = detail;
}

async function api<T>(path: string, body: Record<string, unknown> = {}): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload.ok === false) {
    throw new ApiError(payload.error || `请求失败 (${response.status})`, response.status, payload.code || "");
  }
  return payload as T;
}

type CustomSelect = { wrap: HTMLDivElement; trigger: HTMLButtonElement; sync: () => void };
const customSelects = new Map<HTMLSelectElement, CustomSelect>();

function closeCustomSelect(except?: HTMLDivElement) {
  customSelects.forEach(({ wrap, trigger }) => {
    if (wrap === except) return;
    wrap.classList.remove("is-open");
    trigger.setAttribute("aria-expanded", "false");
  });
}

function upgradeSelect(select: HTMLSelectElement) {
  const wrap = document.createElement("div");
  wrap.className = "cs-wrap cs-wrap--full";
  const trigger = document.createElement("button");
  trigger.type = "button";
  trigger.className = "cs-trigger";
  trigger.setAttribute("aria-haspopup", "listbox");
  trigger.setAttribute("aria-expanded", "false");
  const dropdown = document.createElement("div");
  dropdown.className = "cs-dropdown";
  dropdown.setAttribute("role", "listbox");

  select.parentNode!.insertBefore(wrap, select);
  select.hidden = true;
  wrap.append(trigger, dropdown, select);

  const sync = () => {
    trigger.textContent = select.selectedOptions[0]?.textContent || "请选择";
    trigger.disabled = select.disabled;
    dropdown.replaceChildren();
    Array.from(select.options).forEach((option) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "cs-option";
      button.textContent = option.textContent;
      button.disabled = option.disabled;
      button.setAttribute("role", "option");
      button.setAttribute("aria-selected", String(option.selected));
      button.classList.toggle("is-selected", option.selected);
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        select.value = option.value;
        select.dispatchEvent(new Event("change", { bubbles: true }));
        sync();
        closeCustomSelect();
      });
      dropdown.append(button);
    });
  };

  trigger.addEventListener("click", (event) => {
    event.stopPropagation();
    const willOpen = !wrap.classList.contains("is-open");
    closeCustomSelect();
    wrap.classList.toggle("is-open", willOpen);
    trigger.setAttribute("aria-expanded", String(willOpen));
  });
  customSelects.set(select, { wrap, trigger, sync });
  sync();
}

function setSelectDisabled(select: HTMLSelectElement, disabled: boolean) {
  select.disabled = disabled;
  customSelects.get(select)?.sync();
}

document.addEventListener("click", () => closeCustomSelect());
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeCustomSelect();
});

function targetResolution(): [number, number] {
  if (qualitySelect.value === "2k") return [2560, 1440];
  if (qualitySelect.value === "720p") return [1280, 720];
  return [1920, 1080];
}

function screenEncoder(sourceWidth?: number, sourceHeight?: number) {
  const requestedFrameRate = Number(frameRateSelect.value);
  const frameRate = [30, 60, 120, 144, 240].includes(requestedFrameRate) ? requestedFrameRate : 30;
  const [targetWidth, targetHeight] = targetResolution();
  const width = Math.min(targetWidth, sourceWidth || targetWidth);
  const height = Math.min(targetHeight, sourceHeight || targetHeight);
  if (qualitySelect.value === "2k") {
    return {
      width: { max: width },
      height: { max: height },
      frameRate: { max: frameRate },
      bitrateMin: frameRate >= 120 ? 5000 : frameRate === 60 ? 4500 : 3500,
      bitrateMax: 5000,
    };
  }
  if (qualitySelect.value === "720p") {
    return {
      width: { max: width },
      height: { max: height },
      frameRate: { max: frameRate },
      bitrateMin: frameRate >= 120 ? 3500 : frameRate === 60 ? 2500 : 1500,
      bitrateMax: frameRate >= 60 ? 5000 : 3500,
    };
  }
  return {
    width: { max: width },
    height: { max: height },
    frameRate: { max: frameRate },
    bitrateMin: frameRate >= 120 ? 4500 : frameRate === 60 ? 3500 : 2500,
    bitrateMax: 5000,
  };
}

function updateOutputProfile() {
  const qualityLabel = qualitySelect.value === "2k" ? "2K" : qualitySelect.value;
  outputProfile.textContent = `${qualityLabel} · ${frameRateSelect.value}`;
}

async function renewRtcToken() {
  window.clearTimeout(tokenRenewTimer);
  if (!client || tokenRenewing) return;
  tokenRenewing = true;
  try {
    const fresh = presenterPage
      ? await api<Credentials & { ok: true }>("/screen-share/api/presenter/renew")
      : await api<Credentials & { ok: true }>("/screen-share/api/viewer/token", {
          token: rawLinkToken,
          viewer_instance: viewerInstanceId,
        });
    await client.renewToken(fresh.token);
    const recovered = tokenRenewFailures > 0;
    tokenRenewFailures = 0;
    if (recovered) {
      setStatus(
        presenterPage ? "授权已恢复" : "正在观看",
        presenterPage ? "屏幕共享仍在继续。" : "共享画面已连接。",
        "ok",
      );
    }
  } catch (error) {
    const ended = error instanceof ApiError && [401, 404, 410].includes(error.status);
    if (ended) {
      if (presenterPage) {
        await stopPresenter("server_ended", false);
      } else {
        await client?.leave().catch(() => undefined);
        client = null;
        remoteAudioTracks.forEach((track) => track.stop());
        remoteAudioTracks.clear();
        playButton.hidden = true;
        setStatus("共享已结束", "观看授权已失效。", "idle");
      }
      return;
    }
    tokenRenewFailures += 1;
    const delay = Math.min(30_000, 1000 * (2 ** Math.min(tokenRenewFailures - 1, 5)));
    setStatus(
      "正在恢复授权",
      `Token 续期暂时失败，${Math.ceil(delay / 1000)} 秒后重试。`,
      "warn",
    );
    tokenRenewTimer = window.setTimeout(() => void renewRtcToken(), delay);
  } finally {
    tokenRenewing = false;
  }
}

async function stopPresenter(reason = "presenter_stop", notifyServer = true, showEnded = true) {
  if (stopping) return;
  stopping = true;
  window.clearInterval(heartbeatTimer);
  window.clearTimeout(tokenRenewTimer);
  try {
    if (client) {
      const published = [screenVideo, screenAudio].filter(Boolean) as (ILocalVideoTrack | ILocalAudioTrack)[];
      if (published.length) await client.unpublish(published).catch(() => undefined);
      await client.leave().catch(() => undefined);
    }
  } finally {
    [screenAudio, screenVideo].forEach((track) => track?.close());
    screenAudio = null;
    screenVideo = null;
    client = null;
    if (notifyServer) {
      await fetch("/screen-share/api/presenter/stop", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason }),
        keepalive: true,
      }).catch(() => undefined);
    }
    startButton.hidden = true;
    stopButton.hidden = true;
    setSelectDisabled(qualitySelect, true);
    setSelectDisabled(frameRateSelect, true);
    if (showEnded) setStatus("共享已结束", "可以关闭此页面。", "idle");
  }
}

async function startPresenter() {
  if (!window.isSecureContext && location.hostname !== "localhost" && location.hostname !== "127.0.0.1") {
    setStatus("需要 HTTPS", "浏览器只允许安全页面捕获屏幕和系统声音。", "error");
    return;
  }
  startButton.disabled = true;
  setSelectDisabled(qualitySelect, true);
  setSelectDisabled(frameRateSelect, true);
  setStatus("正在准备", "请在系统窗口中选择要共享的内容。", "idle");
  try {
    const credentials = await api<Credentials & { ok: true }>("/screen-share/api/presenter/claim", { token: rawLinkToken });
    history.replaceState({}, "", "/screen-share/p");
    qualitySelect.value = ["2k", "720p"].includes(credentials.default_quality || "")
      ? credentials.default_quality!
      : "1080p";
    customSelects.get(qualitySelect)?.sync();
    client = AgoraRTC.createClient({ mode: "live", codec: "vp8" });
    await client.setClientRole("host");
    client.on("token-privilege-will-expire", () => void renewRtcToken());
    client.on("token-privilege-did-expire", () => void renewRtcToken());

    const highFrameRate = Number(frameRateSelect.value) > 30;
    const created = await AgoraRTC.createScreenVideoTrack(
      { encoderConfig: screenEncoder(), optimizationMode: highFrameRate || qualitySelect.value === "720p" ? "motion" : "detail" },
      "auto",
    );
    if (Array.isArray(created)) {
      [screenVideo, screenAudio] = created;
    } else {
      screenVideo = created;
    }
    const captureSettings = screenVideo.getMediaStreamTrack().getSettings();
    const sourceWidth = Number(captureSettings.width || 0);
    const sourceHeight = Number(captureSettings.height || 0);
    if (sourceWidth && sourceHeight) {
      await screenVideo.setEncoderConfiguration(screenEncoder(sourceWidth, sourceHeight));
    }
    screenVideo.on("track-ended", () => void stopPresenter("capture_ended"));

    await client.join(credentials.app_id, credentials.channel, credentials.token, credentials.uid);
    const publishTracks = [screenVideo, screenAudio].filter(Boolean) as (ILocalVideoTrack | ILocalAudioTrack)[];
    await client.publish(publishTracks);
    screenVideo.play(stage, { fit: "contain" });
    const ready = await api<{ ok: true; viewer_url: string }>("/screen-share/api/presenter/ready");
    heartbeatTimer = window.setInterval(() => {
      void api("/screen-share/api/presenter/heartbeat")
        .then(() => {
          if (heartbeatFailures > 0) {
            setStatus("连接已恢复", "屏幕共享仍在继续。", "ok");
          }
          heartbeatFailures = 0;
        })
        .catch((error) => {
          if (error instanceof ApiError && (error.status === 401 || error.status === 410)) {
            void stopPresenter("server_ended", false);
            return;
          }
          heartbeatFailures += 1;
          setStatus("正在重新连接", "网络恢复后会自动继续；超过 60 秒仍未恢复时会结束共享。", "warn");
        });
    }, 5000);
    startButton.hidden = true;
    stopButton.hidden = false;
    const audioDescription = screenAudio
      ? "当前仅共享系统声音"
      : "浏览器未提供系统声音，当前仅共享画面";
    const [targetWidth, targetHeight] = targetResolution();
    const resolutionDescription = sourceWidth && sourceHeight && (sourceWidth < targetWidth || sourceHeight < targetHeight)
      ? `源画面为 ${sourceWidth}×${sourceHeight}，保持源分辨率且不放大`
      : "按所选画质上限编码";
    setStatus(
      "正在共享",
      `${resolutionDescription}；${audioDescription}。观看链接已由 Bot 发送到原频道。`,
      screenAudio ? "ok" : "warn",
    );
    if (ready.viewer_url) detailEl.title = ready.viewer_url;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setStatus("无法开始共享", message, "error");
    if (client || screenVideo) await stopPresenter("start_failed", true, false);
    startButton.hidden = true;
    setSelectDisabled(qualitySelect, true);
    setSelectDisabled(frameRateSelect, true);
    setStatus("无法开始共享", `${message}。此单次链接已失效，请回到频道重新发起。`, "error");
  }
}

async function startViewer() {
  setStatus("正在连接", "正在加入屏幕共享…");
  try {
    const credentials = await api<Credentials & { ok: true }>("/screen-share/api/viewer/token", {
      token: rawLinkToken,
      viewer_instance: viewerInstanceId,
    });
    client = AgoraRTC.createClient({ mode: "live", codec: "vp8" });
    await client.setClientRole("audience");
    client.on("token-privilege-will-expire", () => void renewRtcToken());
    client.on("token-privilege-did-expire", () => void renewRtcToken());
    client.on("user-published", async (user, mediaType) => {
      await client!.subscribe(user, mediaType);
      if (mediaType === "video" && user.videoTrack) {
        user.videoTrack.play(stage, { fit: "contain" });
        setStatus("正在观看", "共享画面已连接。", "ok");
      }
      if (mediaType === "audio" && user.audioTrack) {
        remoteAudioTracks.add(user.audioTrack);
        user.audioTrack.play();
      }
    });
    client.on("user-unpublished", (user, mediaType) => {
      if (mediaType === "audio" && user.audioTrack) remoteAudioTracks.delete(user.audioTrack);
    });
    client.on("user-left", () => {
      setStatus("共享已结束", "发起者已经停止共享。", "idle");
      playButton.hidden = true;
    });
    await client.join(credentials.app_id, credentials.channel, credentials.token, credentials.uid);
    setStatus("等待画面", "共享者连接后画面会自动出现。", "idle");
  } catch (error) {
    setStatus("无法观看", error instanceof Error ? error.message : String(error), "error");
  }
}

AgoraRTC.onAutoplayFailed = () => {
  if (presenterPage) return;
  playButton.hidden = false;
  revealViewerControls();
  setStatus("点击开启声音", "浏览器阻止了自动播放。", "warn");
};

playButton.addEventListener("click", async () => {
  await AgoraRTC.resumeAudioContext();
  remoteAudioTracks.forEach((track) => track.play());
  playButton.hidden = true;
});
fullscreenButton.addEventListener("click", async () => {
  if (document.fullscreenElement) {
    await document.exitFullscreen();
  } else {
    await document.documentElement.requestFullscreen();
  }
});
document.addEventListener("fullscreenchange", () => {
  fullscreenButton.textContent = document.fullscreenElement ? "退出全屏" : "全屏";
});
let viewerControlsTimer = 0;
function revealViewerControls() {
  if (presenterPage) return;
  viewerControls.classList.add("is-visible");
  window.clearTimeout(viewerControlsTimer);
  viewerControlsTimer = window.setTimeout(() => viewerControls.classList.remove("is-visible"), 2600);
}
document.addEventListener("pointermove", revealViewerControls);
document.addEventListener("keydown", revealViewerControls);
stage.addEventListener("dblclick", () => {
  if (!presenterPage) fullscreenButton.click();
});
startButton.addEventListener("click", () => void startPresenter());
stopButton.addEventListener("click", () => void stopPresenter("presenter_stop"));
window.addEventListener("pagehide", () => {
  if (presenterPage && client && !stopping) {
    void fetch("/screen-share/api/presenter/stop", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: "page_closed" }),
      keepalive: true,
    });
  }
});

document.body.dataset.mode = presenterPage ? "presenter" : "viewer";
$("title").textContent = presenterPage ? "发起屏幕共享" : "观看屏幕共享";
$("mode-badge").textContent = presenterPage ? "共享控制" : "观看端";
$("subtitle").textContent = presenterPage
  ? "配置屏幕源和视频输出；音频仅使用系统声音。"
  : "此观看链接仅在当前共享会话期间有效。";
controlPanel.hidden = !presenterPage;
panelBar.hidden = !presenterPage;
startButton.hidden = !presenterPage;
qualitySelect.parentElement!.hidden = !presenterPage;
frameRateSelect.parentElement!.hidden = !presenterPage;
stopButton.hidden = true;
upgradeSelect(qualitySelect);
upgradeSelect(frameRateSelect);
qualitySelect.addEventListener("change", updateOutputProfile);
frameRateSelect.addEventListener("change", updateOutputProfile);
updateOutputProfile();

if (!rawLinkToken) {
  setStatus("链接无效", "请从 Bot 发送的链接重新打开。", "error");
  startButton.hidden = true;
} else if (!presenterPage) {
  revealViewerControls();
  void startViewer();
} else {
  setStatus("等待开始", "点击按钮后浏览器会弹出窗口选择器。", "idle");
}
