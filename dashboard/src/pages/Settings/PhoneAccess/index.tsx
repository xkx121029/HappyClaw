import { useCallback, useEffect, useState } from "react";
import { Alert, Button, Popconfirm, Spin, Switch } from "antd";
import {
  Copy,
  Eye,
  EyeOff,
  RefreshCw,
  RotateCcw,
  Smartphone,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { message } from "@/utils/antdMessage";

import {
  phoneAccessApi,
  type PhoneAccessStatus,
} from "../../../api/modules/phoneAccess";
import { useServiceRestartContext } from "../../../context/ServiceRestartContext";
import { TabPanelHeader } from "../AdvancedSettings/TabPanelHeader";
import styles from "./index.module.less";

/**
 * "Phone access" settings: LAN binding + shared credential.
 *
 * Both values are read when the service boots (socket binding and the API
 * middleware), so saving only stages them in ``config.json`` — the panel
 * always surfaces a restart prompt instead of pretending it is live.
 */
export function PhoneAccessPanel() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<PhoneAccessStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [revealToken, setRevealToken] = useState(false);
  const [rotating, setRotating] = useState(false);
  const { requestRestart, isRestarting } = useServiceRestartContext();

  const fetchStatus = useCallback(async () => {
    try {
      setStatus(await phoneAccessApi.get());
    } catch (err) {
      console.error(err);
      message.error(
        t("advancedSettings.phone.loadError", "读取手机访问设置失败"),
      );
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void fetchStatus();
  }, [fetchStatus]);

  const apply = async (body: {
    enabled?: boolean;
    regenerate_token?: boolean;
  }) => {
    setSaving(true);
    try {
      setStatus(await phoneAccessApi.update(body));
    } catch (err) {
      console.error(err);
      message.error(
        t("advancedSettings.phone.saveError", "保存失败，请稍后重试"),
      );
    } finally {
      setSaving(false);
    }
  };

  const rotate = async () => {
    setRotating(true);
    try {
      setStatus(await phoneAccessApi.rotateToken());
      setRevealToken(true);
      message.success(t("advancedSettings.phone.rotated", "访问令牌已重置"));
    } catch (err) {
      console.error(err);
      message.error(
        t("advancedSettings.phone.saveError", "保存失败，请稍后重试"),
      );
    } finally {
      setRotating(false);
    }
  };

  const copy = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      message.success(t("advancedSettings.phone.copied", "已复制"));
    } catch {
      message.error(
        t("advancedSettings.phone.copyFailed", "复制失败，请手动选择文本"),
      );
    }
  };

  if (loading) {
    return (
      <div className={styles.center}>
        <Spin />
      </div>
    );
  }
  if (!status) return null;

  const envManaged = status.managed_by_env;
  const maskedToken = status.token
    ? `${status.token.slice(0, 4)}${"•".repeat(
        Math.max(6, status.token.length - 8),
      )}${status.token.slice(-4)}`
    : "";

  return (
    <div className={styles.page}>
      <TabPanelHeader
        icon={<Smartphone size={18} strokeWidth={1.8} />}
        title={t("advancedSettings.phone.title", "手机访问")}
        description={t(
          "advancedSettings.phone.desc",
          "让同一局域网内的手机浏览器作为客户端操控这台电脑上的 HappyClaw。",
        )}
      />

      <section className={styles.card}>
        <div className={styles.rowBetween}>
          <div className={styles.rowText}>
            <span className={styles.rowTitle}>
              {t("advancedSettings.phone.allow", "允许手机访问")}
            </span>
            <span className={styles.rowDesc}>
              {status.enabled
                ? t(
                    "advancedSettings.phone.allowOnHint",
                    "当前监听 0.0.0.0，局域网内设备可通过下方的网址访问。",
                  )
                : t(
                    "advancedSettings.phone.allowOffHint",
                    "当前仅监听 127.0.0.1，只有本机能访问。",
                  )}
            </span>
          </div>
          <Switch
            checked={status.enabled}
            loading={saving}
            disabled={envManaged}
            onChange={(checked) => void apply({ enabled: checked })}
            aria-label={t("advancedSettings.phone.allow", "允许手机访问")}
          />
        </div>

        <Alert
          type="warning"
          showIcon
          className={styles.notice}
          message={t(
            "advancedSettings.phone.exposureTitle",
            "等同于把服务暴露到局域网",
          )}
          description={t(
            "advancedSettings.phone.exposureDesc",
            "开启后，同一网络内的任何设备只要拿到访问令牌就能操作 HappyClaw：读写会话、文件与命令。请只在可信网络使用，并妥善保管令牌。",
          )}
        />
      </section>

      {status.enabled && (
        <section className={styles.card}>
          <span className={styles.rowTitle}>
            {t("advancedSettings.phone.urlsTitle", "手机端填写这个地址")}
          </span>
          {status.urls.length === 0 ? (
            <p className={styles.empty}>
              {t(
                "advancedSettings.phone.noLan",
                "没有检测到局域网地址，请确认电脑已连接 Wi-Fi 或网线。",
              )}
            </p>
          ) : (
            <ul className={styles.urlList}>
              {status.urls.map((url) => (
                <li key={url} className={styles.urlRow}>
                  <code className={styles.urlCode}>{url}</code>
                  <Button
                    size="small"
                    type="text"
                    icon={<Copy size={15} />}
                    onClick={() => void copy(url)}
                    aria-label={t("advancedSettings.phone.copy", "复制")}
                  >
                    {t("advancedSettings.phone.copy", "复制")}
                  </Button>
                </li>
              ))}
            </ul>
          )}

          <div className={styles.tokenBox}>
            <span className={styles.rowDesc}>
              {t("advancedSettings.phone.tokenLabel", "访问令牌")}
            </span>
            <div className={styles.tokenRow}>
              <code className={styles.tokenCode}>
                {status.token
                  ? revealToken
                    ? status.token
                    : maskedToken
                  : t("advancedSettings.phone.noToken", "尚未生成")}
              </code>
              {status.token ? (
                <>
                  <Button
                    size="small"
                    type="text"
                    icon={
                      revealToken ? <EyeOff size={15} /> : <Eye size={15} />
                    }
                    onClick={() => setRevealToken((prev) => !prev)}
                    aria-label={t(
                      "advancedSettings.phone.toggleToken",
                      "显示或隐藏令牌",
                    )}
                  />
                  <Button
                    size="small"
                    type="text"
                    icon={<Copy size={15} />}
                    onClick={() => void copy(status.token)}
                    aria-label={t("advancedSettings.phone.copy", "复制")}
                  />
                </>
              ) : null}
              <Popconfirm
                title={t(
                  "advancedSettings.phone.rotateConfirm",
                  "重置访问令牌？",
                )}
                description={t(
                  "advancedSettings.phone.rotateConfirmDesc",
                  "已连接的手机需要重新输入新令牌，重启后生效。",
                )}
                okText={t("advancedSettings.phone.rotate", "重置")}
                cancelText={t("common.cancel", "取消")}
                onConfirm={() => void rotate()}
              >
                <Button
                  size="small"
                  icon={<RotateCcw size={15} />}
                  loading={rotating}
                  disabled={envManaged}
                >
                  {t("advancedSettings.phone.rotate", "重置")}
                </Button>
              </Popconfirm>
            </div>
          </div>
        </section>
      )}

      {envManaged && (
        <Alert
          type="info"
          showIcon
          message={t(
            "advancedSettings.phone.envManaged",
            "当前由环境变量管理（OCTOP_BIND_HOST / OCTOP_ACCESS_TOKEN），此处修改不会覆盖。",
          )}
        />
      )}

      {status.restart_required ? (
        <Alert
          type="warning"
          showIcon
          message={t(
            "advancedSettings.phone.restartTitle",
            "设置已保存，需要重启后生效",
          )}
          description={
            <div className={styles.restartBody}>
              <span>
                {t(
                  "advancedSettings.phone.restartDesc",
                  "监听地址与访问令牌只在服务启动时读取，无法热生效。重启后手机才能连接；已经连接的手机需重新确认地址。",
                )}
              </span>
              <span className={styles.restartActions}>
                <Button
                  type="primary"
                  size="small"
                  icon={<RefreshCw size={14} />}
                  loading={isRestarting}
                  onClick={requestRestart}
                >
                  {t("advancedSettings.phone.restartNow", "立即重启")}
                </Button>
                <Button
                  size="small"
                  type="text"
                  onClick={() => void copy("octop restart")}
                >
                  octop restart
                </Button>
              </span>
              <span className={styles.configPath}>{status.config_path}</span>
            </div>
          }
        />
      ) : null}
    </div>
  );
}

export default PhoneAccessPanel;
