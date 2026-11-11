import { useSyncExternalStore } from "react";
import type { OctopUser } from "../api/modules/auth";

/**
 * 单人本机模式：控制台不再有「当前登录用户」这个概念。
 *
 * 这里只保存一份保存在浏览器本地的偏好画像（显示名 / 头像），
 * 不请求 ``/auth/me``、不持有角色、不做权限判断。组件里历史遗留的
 * ``useCurrentUser()`` 调用统一读这份本机画像，保持类型兼容。
 */
const LOCAL_PROFILE_KEY = "octop:local-profile:v1";

interface LocalProfilePrefs {
  display_name: string;
  avatar_icon: string | null;
  avatar_url: string | null;
}

const DEFAULT_PREFS: LocalProfilePrefs = {
  display_name: "我",
  avatar_icon: null,
  avatar_url: null,
};

function readPrefs(): LocalProfilePrefs {
  try {
    const raw = localStorage.getItem(LOCAL_PROFILE_KEY);
    if (!raw) return { ...DEFAULT_PREFS };
    const parsed = JSON.parse(raw) as Partial<LocalProfilePrefs> | null;
    if (!parsed || typeof parsed !== "object") return { ...DEFAULT_PREFS };
    return {
      display_name:
        typeof parsed.display_name === "string" && parsed.display_name.trim()
          ? parsed.display_name
          : DEFAULT_PREFS.display_name,
      avatar_icon:
        typeof parsed.avatar_icon === "string" ? parsed.avatar_icon : null,
      avatar_url:
        typeof parsed.avatar_url === "string" ? parsed.avatar_url : null,
    };
  } catch {
    return { ...DEFAULT_PREFS };
  }
}

let prefs = readPrefs();
let snapshot: OctopUser = buildSnapshot();
const listeners = new Set<() => void>();

function buildSnapshot(): OctopUser {
  return {
    // ``id`` 仅用于历史组件里的归属比较；本机只有一个使用者。
    id: 1,
    username: "local",
    // 后端改造完成前仍保留该字段以兼容类型；前端不再读取或展示角色。
    role: "admin",
    permissions: [],
    display_name: prefs.display_name,
    locale: "zh",
    avatar_icon: prefs.avatar_icon,
    avatar_url: prefs.avatar_url,
  };
}

function emit() {
  snapshot = buildSnapshot();
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** 本机偏好画像（静态快照，不触发网络请求）。 */
export function useCurrentUser(): OctopUser {
  return useSyncExternalStore(subscribe, () => snapshot, () => snapshot);
}

/** 更新本机显示名 / 头像，写入 localStorage 并通知界面刷新。 */
export function updateLocalProfile(patch: Partial<LocalProfilePrefs>): void {
  prefs = { ...prefs, ...patch };
  try {
    localStorage.setItem(LOCAL_PROFILE_KEY, JSON.stringify(prefs));
  } catch {
    /* 隐私模式下写不进去也不影响本次会话 */
  }
  emit();
}

/**
 * 历史组件（团队用户管理页）仍会调用它；单人模式下只更新本机偏好。
 * 这些页面已经不再挂到路由上。
 */
export function useSetCurrentUser() {
  return (next: OctopUser | null | ((prev: OctopUser | null) => OctopUser | null)) => {
    const value = typeof next === "function" ? next(snapshot) : next;
    if (!value) return;
    updateLocalProfile({
      display_name: value.display_name || DEFAULT_PREFS.display_name,
      avatar_icon: value.avatar_icon ?? null,
      avatar_url: value.avatar_url ?? null,
    });
  };
}
