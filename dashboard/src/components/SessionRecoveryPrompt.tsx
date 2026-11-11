import { useEffect, useState } from "react";
import { Button, Modal } from "antd";
import { useTranslation } from "react-i18next";
import { UNAUTHORIZED_EVENT } from "../api/request";

/**
 * 单人本机模式的 401 恢复入口。
 *
 * 登录页已经下线，会话凭证失效时不能再把人踢去一个不存在的页面。
 * 这里给出可读的中文说明和两条明确动作：重新连接（刷新并重新探测本机
 * 服务）或稍后处理。
 */
export default function SessionRecoveryPrompt() {
  const { t } = useTranslation();
  const [lost, setLost] = useState(false);

  useEffect(() => {
    const handler = (event: Event) => {
      event.preventDefault();
      setLost(true);
    };
    window.addEventListener(UNAUTHORIZED_EVENT, handler);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, handler);
  }, []);

  const reconnect = () => {
    setLost(false);
    window.location.reload();
  };

  return (
    <Modal
      open={lost}
      title={t("errors.sessionExpiredTitle", "本机连接已失效")}
      onCancel={() => setLost(false)}
      footer={[
        <Button key="later" onClick={() => setLost(false)}>
          {t("errors.sessionExpiredLater", "稍后处理")}
        </Button>,
        <Button key="reconnect" type="primary" onClick={reconnect}>
          {t("errors.sessionExpiredReconnect", "重新连接")}
        </Button>,
      ]}
    >
      <p>
        {t(
          "errors.sessionExpiredBody",
          "这台设备上的访问凭证已过期，部分操作会失败。重新连接会刷新页面并重新探测本机服务；如果仍然失败，请确认 HappyClaw 后端仍在运行。",
        )}
      </p>
    </Modal>
  );
}
