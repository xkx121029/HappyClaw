import { useSyncExternalStore } from "react";

interface ToastItem {
  id: number;
  text: string;
}

let items: ToastItem[] = [];
let seq = 0;
const listeners = new Set<() => void>();

function emit() {
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function getSnapshot() {
  return items;
}

/** Lightweight toast used instead of antd's message API. */
export function showMobileToast(text: string, duration = 2200) {
  const id = ++seq;
  items = [...items, { id, text }];
  emit();
  window.setTimeout(() => {
    items = items.filter((item) => item.id !== id);
    emit();
  }, duration);
}

export function MobileToastHost() {
  const list = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  if (list.length === 0) return null;
  return (
    <div className="m-portal m-toast-layer">
      {list.map((item) => (
        <div className="m-toast" key={item.id} role="status">
          {item.text}
        </div>
      ))}
    </div>
  );
}
