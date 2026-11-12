import { useEffect, useState } from "react";

/**
 * 把高频输入折叠成低频值：输入框保持即时响应，过滤/请求用返回值。
 * 默认 180ms，足够跨过一次连续按键，又不会让人感觉列表迟钝。
 */
export function useDebouncedValue<T>(value: T, delay = 180): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);

  return debounced;
}
