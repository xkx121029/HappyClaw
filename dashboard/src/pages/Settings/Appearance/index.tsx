import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Button,
  Card,
  Collapse,
  ColorPicker,
  Input,
  InputNumber,
  Radio,
  Segmented,
  Space,
  Tag,
  Tooltip,
  Typography,
  message,
} from "antd";
import { CloudDownloadOutlined, CloudUploadOutlined, ReloadOutlined } from "@ant-design/icons";

import { useTheme } from "../../../context/ThemeContext";
import { setAppearance as commitAppearance } from "../../../styles/appearance/useAppearance";
import { useAppearance } from "../../../styles/appearance/useAppearance";
import { PACKS } from "../../../styles/appearance/packs";
import {
  APPEARANCE_EXPORT_MARKER,
  FONT_FAMILIES,
  FONT_SIZE_CHOICES,
  DENSITIES,
  RADIUS_CHOICES,
  checkCustomCss,
  exportAppearance,
  importAppearance,
  isDefaultAppearance,
  type AppearanceSettings,
  type Density,
  type FontFamilyChoice,
  type FontSizeChoice,
  type RadiusChoice,
  type ThemePack,
} from "../../../styles/appearance/settings";
import { radiusPx } from "../../../styles/appearance/derive";
import { contrastRatio, normalizeHexColor } from "../../../styles/themePalettes";

import styles from "./index.module.less";

/** Preview surfaces: enough shapes to judge radius, density and type at once. */
function Preview() {
  const { t } = useTranslation();
  return (
    <div className={styles.preview} aria-label={t("appearance.preview.label")}>
      <div className={styles.previewRow}>
        <Button type="primary">{t("appearance.preview.primary")}</Button>
        <Button>{t("appearance.preview.secondary")}</Button>
        <Input placeholder={t("appearance.preview.placeholder")} style={{ width: 160 }} />
        <Segmented options={[t("appearance.preview.one"), t("appearance.preview.two")]} />
      </div>
      <div className={styles.previewRow}>
        <Tag color="blue">{t("appearance.preview.tag")}</Tag>
        <Tag>{t("appearance.preview.tagNeutral")}</Tag>
        <Typography.Text type="secondary">{t("appearance.preview.caption")}</Typography.Text>
      </div>
      <div className={styles.bubbleRows}>
        <div className={styles.bubbleUser}>{t("appearance.preview.userBubble")}</div>
        <div className={styles.bubbleAgent}>{t("appearance.preview.agentBubble")}</div>
      </div>
      <pre className={styles.code}>{`const radius = "custom";`}</pre>
    </div>
  );
}

export default function AppearanceSettingsPage() {
  const { t } = useTranslation();
  const { palette, setPalette, setPreference, mode, customColor, setCustomColor } = useTheme();
  const appearance = useAppearance();
  const setAppearance = commitAppearance;
  const [draftCss, setDraftCss] = useState(appearance.customCss);
  const [importText, setImportText] = useState("");

  const patch = useCallback(
    (next: Partial<AppearanceSettings>) => setAppearance({ ...appearance, ...next }),
    [appearance, setAppearance],
  );

  const applyPack = (pack: ThemePack) => {
    const definition = PACKS[pack];
    setAppearance({ ...definition.settings });
    setPalette(definition.palette);
    setPreference(pack === "default" ? "system" : definition.preference);
  };

  const customCheck = checkCustomCss(draftCss);
  const cssErrors = useMemo(
    () => ({
      import: t("appearance.customCss.errors.import"),
      remoteUrl: t("appearance.customCss.errors.remoteUrl"),
      script: t("appearance.customCss.errors.script"),
      unbalanced: t("appearance.customCss.errors.unbalanced"),
    }),
    [t],
  );

  const brandHex = palette === "custom" ? customColor : undefined;
  const contrast = useMemo(() => {
    const hex = normalizeHexColor(brandHex ?? "") ?? null;
    if (!hex) return null;
    const bg = mode === "dark" ? "#161616" : "#ffffff";
    return contrastRatio(hex, bg);
  }, [brandHex, mode]);

  const copyExport = async () => {
    try {
      await navigator.clipboard.writeText(exportAppearance(appearance));
      message.success(t("appearance.export.copied"));
    } catch {
      message.error(t("appearance.export.copyFailed"));
    }
  };

  const doImport = () => {
    const result = importAppearance(importText);
    if (!result.ok || !result.settings) {
      message.error(t("appearance.import.invalid"));
      return;
    }
    setAppearance(result.settings);
    setDraftCss(result.settings.customCss);
    setImportText("");
    message.success(t("appearance.import.done"));
  };

  return (
    <div className={styles.page}>
      <Card
        title={t("appearance.livePreview")}
        extra={
          <Button
            size="small"
            icon={<ReloadOutlined />}
            disabled={isDefaultAppearance(appearance)}
            onClick={() => {
              applyPack("default");
              setDraftCss("");
            }}
          >
            {t("appearance.resetAll")}
          </Button>
        }
      >
        <Preview />
      </Card>

      <Card title={t("appearance.packs.title")} extra={<Typography.Text type="secondary">{t("appearance.packs.hint")}</Typography.Text>}>
        <div className={styles.packGrid}>
          {(Object.keys(PACKS) as ThemePack[]).map((id) => (
            <button
              key={id}
              type="button"
              className={appearance.pack === id ? `${styles.packCard} ${styles.packActive}` : styles.packCard}
              onClick={() => applyPack(id)}
            >
              <span className={styles.packSwatch} data-pack={id} />
              <span className={styles.packName}>{t(`appearance.packs.${id}`)}</span>
              <span className={styles.packDesc}>{t(`appearance.packs.${id}Desc`)}</span>
            </button>
          ))}
        </div>
      </Card>

      <Card title={t("appearance.brand.title")} extra={<Typography.Text type="secondary">{t("appearance.brand.hint")}</Typography.Text>}>
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <Radio.Group
            value={palette}
            onChange={(event) => setPalette(event.target.value)}
            optionType="button"
            buttonStyle="solid"
          >
            <Radio.Button value="rose">{t("appearance.brand.rose")}</Radio.Button>
            <Radio.Button value="tech">{t("appearance.brand.tech")}</Radio.Button>
            <Radio.Button value="indigo">{t("appearance.brand.indigo")}</Radio.Button>
            <Radio.Button value="teal">{t("appearance.brand.teal")}</Radio.Button>
            <Radio.Button value="violet">{t("appearance.brand.violet")}</Radio.Button>
            <Radio.Button value="emerald">{t("appearance.brand.emerald")}</Radio.Button>
            <Radio.Button value="amber">{t("appearance.brand.amber")}</Radio.Button>
            <Radio.Button value="custom">{t("appearance.brand.custom")}</Radio.Button>
          </Radio.Group>
          <Space align="center">
            <ColorPicker
              value={brandHex ?? "#4B74FA"}
              onChangeComplete={(color) => {
                setPalette("custom");
                setCustomColor(color.toHexString());
              }}
              showText
            />
            <Typography.Text type="secondary">{t("appearance.brand.customHint")}</Typography.Text>
          </Space>
          {contrast !== null && contrast < 4.5 ? (
            <Alert
              type="warning"
              showIcon
              message={t("appearance.brand.lowContrast", { ratio: contrast.toFixed(2) })}
              description={t("appearance.brand.lowContrastHint")}
            />
          ) : null}
        </Space>
      </Card>

      <Card title={t("appearance.radius.title")} extra={<Typography.Text type="secondary">{t("appearance.radius.hint")}</Typography.Text>}>
        <Space size="middle" wrap>
          <Segmented
            value={appearance.radius}
            onChange={(value) => patch({ radius: value as RadiusChoice })}
            options={[
              { label: t("appearance.radius.default"), value: "default" },
              ...RADIUS_CHOICES.map((value) => ({ label: `${value}px`, value })),
            ]}
          />
          {appearance.radius === "custom" ? (
            <InputNumber
              min={0}
              max={64}
              value={radiusPx(appearance) ?? 8}
              onChange={(value) => patch({ customRadius: typeof value === "number" ? value : 8 })}
              addonAfter="px"
            />
          ) : null}
        </Space>
      </Card>

      <Card title={t("appearance.density.title")} extra={<Typography.Text type="secondary">{t("appearance.density.hint")}</Typography.Text>}>
        <Segmented
          value={appearance.density}
          onChange={(value) => patch({ density: value as Density })}
          options={DENSITIES.map((value) => ({ label: t(`appearance.density.${value}`), value }))}
        />
      </Card>

      <Card title={t("appearance.fontSize.title")} extra={<Typography.Text type="secondary">{t("appearance.fontSize.hint")}</Typography.Text>}>
        <Segmented
          value={appearance.fontSize}
          onChange={(value) => patch({ fontSize: value as FontSizeChoice })}
          options={FONT_SIZE_CHOICES.map((value) => ({ label: t(`appearance.fontSize.${value}`), value }))}
        />
      </Card>

      <Card title={t("appearance.fontFamily.title")} extra={<Typography.Text type="secondary">{t("appearance.fontFamily.hint")}</Typography.Text>}>
        <Segmented
          value={appearance.fontFamily}
          onChange={(value) => patch({ fontFamily: value as FontFamilyChoice })}
          options={FONT_FAMILIES.map((value) => ({ label: t(`appearance.fontFamily.${value}`), value }))}
        />
      </Card>

      <Card>
        <Collapse
          ghost
          items={[
            {
              key: "css",
              label: t("appearance.customCss.title"),
              children: (
                <Space direction="vertical" style={{ width: "100%" }}>
                  <Typography.Text type="secondary">{t("appearance.customCss.hint")}</Typography.Text>
                  <Input.TextArea
                    value={draftCss}
                    onChange={(event) => setDraftCss(event.target.value)}
                    autoSize={{ minRows: 6, maxRows: 16 }}
                    spellCheck={false}
                    className={styles.cssBox}
                  />
                  {!customCheck.ok ? (
                    <Alert type="error" showIcon message={cssErrors[customCheck.reason ?? "unbalanced"]} />
                  ) : null}
                  <Space>
                    <Button
                      type="primary"
                      disabled={!customCheck.ok}
                      onClick={() => patch({ customCss: draftCss })}
                    >
                      {t("appearance.customCss.apply")}
                    </Button>
                    <Button
                      disabled={!appearance.customCss}
                      onClick={() => {
                        setDraftCss("");
                        patch({ customCss: "" });
                      }}
                    >
                      {t("appearance.customCss.clear")}
                    </Button>
                  </Space>
                </Space>
              ),
            },
            {
              key: "transfer",
              label: t("appearance.transfer.title"),
              children: (
                <Space direction="vertical" style={{ width: "100%" }}>
                  <Space>
                    <Button icon={<CloudDownloadOutlined />} onClick={() => void copyExport()}>
                      {t("appearance.export.copy")}
                    </Button>
                    <Tooltip title={t("appearance.export.markerHint", { marker: APPEARANCE_EXPORT_MARKER })}>
                      <Typography.Text type="secondary">{t("appearance.export.hint")}</Typography.Text>
                    </Tooltip>
                  </Space>
                  <Input.TextArea
                    value={importText}
                    onChange={(event) => setImportText(event.target.value)}
                    placeholder={t("appearance.import.placeholder")}
                    autoSize={{ minRows: 4, maxRows: 10 }}
                    spellCheck={false}
                  />
                  <Button icon={<CloudUploadOutlined />} disabled={!importText.trim()} onClick={doImport}>
                    {t("appearance.import.apply")}
                  </Button>
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Typography.Paragraph type="secondary" className={styles.footnote}>
        {t("appearance.storageHint")}
      </Typography.Paragraph>
    </div>
  );
}
