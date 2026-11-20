import { useEffect, useState } from "react";
import { Button, ColorPicker, Input, Switch, message } from "antd";
import type { AggregationColor } from "antd/es/color-picker/color";
import { useTranslation } from "react-i18next";
import cx from "classnames";

import { Mascot } from "../../../../components/Mascot";
import type { MascotInk, MascotShape } from "../../../../components/Mascot";
import {
  MIN_CONTRAST,
  contrastRatio,
  normalizeHex,
  readableOn,
  readRootHex,
} from "../../../../components/Mascot/color";
import {
  MASCOT_INKS,
  MASCOT_SHAPES,
} from "../../../../components/Mascot/engine";
import { useBao } from "../../../../components/Bao/BaoContext";
import type { BaoAppearance } from "../../../../components/Bao/BaoContext";
import { apiErrorMessage } from "../../../../utils/apiError";
import styles from "./BaoPanel.module.less";

const FALLBACK_BRAND = "#c9435c";
/** Placeholder for the custom swatch before the user picks anything. */
const CUSTOM_PREVIEW =
  "conic-gradient(#f87171, #fbbf24, #34d399, #60a5fa, #a78bfa, #f87171)";

/**
 * User-level Bao appearance. Everything is stored in
 * ``users.preferences_json.bao`` through the same endpoint as the name, and
 * the shell context fans the values out to the sidebar, project row, Bao page
 * and push signature.
 *
 * Colours can come from the engine inks or a free pick, but a body that would
 * vanish into the current surface is lifted to the minimum contrast before it
 * is saved; the renderer repeats that check so values saved on the other theme
 * still show up.
 */
export default function BaoPanel() {
  const { t } = useTranslation();
  const { name, appearance, setName, setAppearance, openOnboarding } = useBao();
  const [draftName, setDraftName] = useState(name);
  const [draft, setDraft] = useState<BaoAppearance>(appearance);

  useEffect(() => setDraftName(name), [name]);
  useEffect(() => setDraft(appearance), [appearance]);

  const surfaceHex = readRootHex("--fn-bg-base", "#ffffff");
  const brandHex = readRootHex("--fn-color-brand", FALLBACK_BRAND);
  const effectiveBody = draft.followTheme
    ? brandHex
    : draft.bodyColor
      ? readableOn(draft.bodyColor, surfaceHex)
      : null;

  const commitName = async () => {
    const next = draftName.trim().slice(0, 12);
    if (!next) {
      setDraftName(name);
      return;
    }
    if (next === name) {
      setDraftName(next);
      return;
    }
    try {
      await setName(next);
      message.success(t("personalization.bao.nameSaved"));
    } catch (err) {
      setDraftName(name);
      message.error(apiErrorMessage(err, t("personalization.bao.saveFailed")));
    }
  };

  const persist = (patch: Parameters<typeof setAppearance>[0]) => {
    void setAppearance(patch).catch((err) => {
      setDraft(appearance);
      message.error(apiErrorMessage(err, t("personalization.bao.saveFailed")));
    });
  };

  const chooseShape = (shape: MascotShape) => {
    setDraft((prev) => ({ ...prev, shape }));
    persist({ shape });
  };

  const chooseInk = (color: MascotInk) => {
    setDraft((prev) => ({
      ...prev,
      color,
      bodyColor: null,
      followTheme: false,
    }));
    persist({ color, body_color: null, follow_theme: false });
  };

  const chooseFollowTheme = (followTheme: boolean) => {
    setDraft((prev) => ({ ...prev, followTheme }));
    persist({ follow_theme: followTheme });
  };

  const chooseBodyColor = (color: AggregationColor) => {
    const picked = normalizeHex(color.toHexString());
    if (!picked) return;
    const safe = readableOn(picked, surfaceHex, MIN_CONTRAST);
    if (safe !== picked) {
      message.info(t("personalization.bao.contrastAdjusted", { color: safe }));
    }
    setDraft((prev) => ({ ...prev, bodyColor: safe, followTheme: false }));
    persist({ body_color: safe, follow_theme: false });
  };

  const chooseEyeColor = (color: AggregationColor) => {
    const picked = normalizeHex(color.toHexString());
    if (!picked) return;
    // Eyes are drawn on the body. When the body is an engine ink or the theme
    // brand the renderer knows the final colour and lifts it there; lifting
    // against the page surface here would darken a light pick for no reason.
    const safe = effectiveBody
      ? readableOn(picked, effectiveBody, MIN_CONTRAST)
      : picked;
    if (safe !== picked) {
      message.info(t("personalization.bao.contrastAdjusted", { color: safe }));
    }
    setDraft((prev) => ({ ...prev, eyeColor: safe }));
    persist({ eye_color: safe });
  };

  const resetEyeColor = () => {
    setDraft((prev) => ({ ...prev, eyeColor: null }));
    persist({ eye_color: null });
  };

  const bodySwatch = draft.followTheme
    ? brandHex
    : draft.bodyColor
      ? readableOn(draft.bodyColor, surfaceHex)
      : null;
  const bodyRatio = bodySwatch ? contrastRatio(bodySwatch, surfaceHex) : null;

  return (
    <div className={styles.wrap}>
      <div className={styles.previewCard}>
        <Mascot
          size={132}
          {...draft}
          state="idle"
          surface="var(--fn-bg-elevated)"
          className={styles.preview}
        />
        <div className={styles.previewName}>{draftName || name}</div>
        <p className={styles.previewHint}>
          {t("personalization.bao.previewHint")}
        </p>
      </div>

      <div className={styles.controls}>
        <section className={styles.section}>
          <h3 className={styles.heading}>{t("personalization.bao.name")}</h3>
          <Input
            value={draftName}
            maxLength={12}
            allowClear
            placeholder={t("bao.identity.namePlaceholder")}
            onChange={(event) => setDraftName(event.target.value)}
            onBlur={commitName}
            onPressEnter={(event) => event.currentTarget.blur()}
            className={styles.nameInput}
          />
          <p className={styles.hint}>{t("personalization.bao.nameHint")}</p>
        </section>

        <section className={styles.section}>
          <h3 className={styles.heading}>{t("personalization.bao.shape")}</h3>
          <div
            className={styles.grid}
            role="radiogroup"
            aria-label={t("personalization.bao.shape")}
          >
            {MASCOT_SHAPES.map((value) => (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={draft.shape === value}
                aria-label={t(`personalization.bao.shapes.${value}`)}
                title={t(`personalization.bao.shapes.${value}`)}
                className={cx(
                  styles.swatch,
                  draft.shape === value && styles.swatchActive,
                )}
                onClick={() => chooseShape(value)}
              >
                <Mascot
                  size={40}
                  {...draft}
                  shape={value}
                  paused
                  surface="var(--fn-bg-elevated)"
                />
              </button>
            ))}
          </div>
        </section>

        <section className={styles.section}>
          <div className={styles.headingRow}>
            <h3 className={styles.heading}>
              {t("personalization.bao.bodyColor")}
            </h3>
            <label className={styles.switchRow}>
              <Switch
                size="small"
                checked={draft.followTheme}
                onChange={chooseFollowTheme}
              />
              <span>{t("personalization.bao.followTheme")}</span>
            </label>
          </div>
          <div
            className={cx(styles.grid, draft.followTheme && styles.gridMuted)}
            role="radiogroup"
            aria-label={t("personalization.bao.bodyColor")}
          >
            {MASCOT_INKS.map((value) => {
              const active =
                !draft.followTheme &&
                !draft.bodyColor &&
                draft.color === value;
              return (
                <button
                  key={value}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  aria-label={t(`personalization.bao.inks.${value}`)}
                  title={t(`personalization.bao.inks.${value}`)}
                  className={cx(
                    styles.swatch,
                    styles.inkSwatch,
                    active && styles.swatchActive,
                  )}
                  disabled={draft.followTheme}
                  onClick={() => chooseInk(value)}
                >
                  <Mascot
                    size={32}
                    {...draft}
                    color={value}
                    bodyColor={null}
                    followTheme={false}
                    paused
                    surface="var(--fn-bg-elevated)"
                  />
                </button>
              );
            })}
            <ColorPicker
              value={bodySwatch ?? brandHex}
              disabledAlpha
              disabled={draft.followTheme}
              onChangeComplete={chooseBodyColor}
            >
              <span
                role="button"
                tabIndex={0}
                className={cx(
                  styles.swatch,
                  styles.inkSwatch,
                  styles.customSwatch,
                  !draft.followTheme && !!draft.bodyColor && styles.swatchActive,
                )}
                aria-label={t("personalization.bao.customColor")}
                title={t("personalization.bao.customColor")}
              >
                <span
                  className={styles.customDot}
                  style={{ background: bodySwatch ?? CUSTOM_PREVIEW }}
                  aria-hidden
                />
              </span>
            </ColorPicker>
          </div>
          {bodyRatio !== null ? (
            <p className={styles.hint}>
              {t("personalization.bao.contrastHint", {
                ratio: bodyRatio.toFixed(1),
              })}
            </p>
          ) : (
            <p className={styles.hint}>
              {t("personalization.bao.contrastFloorHint")}
            </p>
          )}
        </section>

        <section className={styles.section}>
          <h3 className={styles.heading}>
            {t("personalization.bao.eyeColor")}
          </h3>
          <div
            className={styles.grid}
            role="radiogroup"
            aria-label={t("personalization.bao.eyeColor")}
          >
            <button
              type="button"
              role="radio"
              aria-checked={!draft.eyeColor}
              className={cx(
                styles.swatch,
                styles.inkSwatch,
                styles.eyeDefault,
                !draft.eyeColor && styles.swatchActive,
              )}
              title={t("personalization.bao.eyeDefault")}
              onClick={resetEyeColor}
            >
              {t("personalization.bao.eyeDefault")}
            </button>
            <ColorPicker
              value={draft.eyeColor ?? brandHex}
              disabledAlpha
              onChangeComplete={chooseEyeColor}
            >
              <span
                role="button"
                tabIndex={0}
                className={cx(
                  styles.swatch,
                  styles.inkSwatch,
                  styles.customSwatch,
                  !!draft.eyeColor && styles.swatchActive,
                )}
                aria-label={t("personalization.bao.customColor")}
                title={t("personalization.bao.customColor")}
              >
                <span
                  className={styles.customDot}
                  style={{ background: draft.eyeColor ?? CUSTOM_PREVIEW }}
                  aria-hidden
                />
              </span>
            </ColorPicker>
          </div>
          <p className={styles.hint}>
            {t("personalization.bao.eyeHint")}
          </p>
        </section>

        <section className={styles.section}>
          <h3 className={styles.heading}>
            {t("personalization.bao.guideTitle", "首次引导")}
          </h3>
          <p className={styles.hint}>
            {t(
              "personalization.bao.guideHint",
              "模型、专家、工作区和健康检查，跟着走一遍就能确认这台机器能不能开始干活。",
            )}
          </p>
          <Button onClick={openOnboarding}>
            {t("personalization.bao.guideOpen", "重新查看首次引导")}
          </Button>
        </section>
      </div>
    </div>
  );
}
