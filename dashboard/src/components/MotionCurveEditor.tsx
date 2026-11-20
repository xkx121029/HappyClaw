import { Button, Segmented, Slider } from "antd";
import { RotateCcw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useMotion } from "../motion";
import type { Bezier, MotionCurvePreset, MotionSpeed } from "../motion";
import styles from "./MotionCurveEditor.module.less";

const CURVE_OPTIONS: { value: MotionCurvePreset; key: string }[] = [
  { value: "comfort", key: "account.motionCurveComfort" },
  { value: "smooth", key: "account.motionCurveSmooth" },
  { value: "swift", key: "account.motionCurveSwift" },
  { value: "spring", key: "account.motionCurveSpring" },
  { value: "custom", key: "account.motionCurveCustom" },
];

const SPEED_OPTIONS: { value: MotionSpeed; key: string }[] = [
  { value: "gentle", key: "account.motionSpeedGentle" },
  { value: "standard", key: "account.motionSpeedStandard" },
  { value: "brisk", key: "account.motionSpeedBrisk" },
];

/** 曲线画布内的归一化坐标。留出 8px 边距，y 轴向上为正。 */
const PAD = 10;
const SIZE = 120;
const SPAN = SIZE - PAD * 2;

function px(x: number): number {
  return PAD + x * SPAN;
}

function py(y: number): number {
  return PAD + (1 - y) * SPAN;
}

function point(x: number, y: number): string {
  return `${px(x)} ${py(y)}`;
}

/**
 * 个性化设置里的动效偏好：曲线、速度、自定义贝塞尔与手感预览。
 * 选择会立即写入全站 CSS 变量并持久化到本机。
 */
export default function MotionCurveEditor() {
  const { t } = useTranslation();
  const { prefs, tokens, reduced, setCurve, setSpeed, setCustomCurve, reset } =
    useMotion();

  const bezier: Bezier = prefs.custom;
  const [x1, y1, x2, y2] = bezier;

  const updatePoint = (index: number, value: number) => {
    const next = [...bezier] as Bezier;
    next[index] = value;
    setCustomCurve(next);
    if (prefs.curve !== "custom") setCurve("custom");
  };

  return (
    <div className={styles.wrap}>
      <Segmented
        block
        size="small"
        value={prefs.curve}
        options={CURVE_OPTIONS.map((o) => ({
          label: t(o.key),
          value: o.value,
        }))}
        onChange={(value) => setCurve(value as MotionCurvePreset)}
      />

      <div className={styles.speedRow}>
        <span className={styles.speedLabel}>
          {t("account.motionSpeed", "速度")}
        </span>
        <Segmented
          size="small"
          value={prefs.speed}
          options={SPEED_OPTIONS.map((o) => ({
            label: t(o.key),
            value: o.value,
          }))}
          onChange={(value) => setSpeed(value as MotionSpeed)}
        />
      </div>

      {prefs.curve === "custom" ? (
        <div className={styles.custom}>
          <svg
            className={styles.curveCanvas}
            viewBox={`0 0 ${SIZE} ${SIZE}`}
            role="img"
            aria-label="cubic-bezier"
          >
            <rect
              x={PAD}
              y={PAD}
              width={SPAN}
              height={SPAN}
              className={styles.curveFrame}
            />
            <line
              x1={PAD}
              y1={PAD + SPAN}
              x2={PAD + SPAN}
              y2={PAD}
              className={styles.curveDiagonal}
            />
            <path
              d={`M ${point(0, 0)} C ${point(x1, y1)} ${point(x2, y2)} ${point(1, 1)}`}
              className={styles.curvePath}
            />
            <line
              x1={px(0)}
              y1={py(0)}
              x2={px(x1)}
              y2={py(y1)}
              className={styles.curveHandleLine}
            />
            <line
              x1={px(1)}
              y1={py(1)}
              x2={px(x2)}
              y2={py(y2)}
              className={styles.curveHandleLine}
            />
            <circle cx={px(0)} cy={py(0)} r={3.2} className={styles.curveAnchor} />
            <circle cx={px(1)} cy={py(1)} r={3.2} className={styles.curveAnchor} />
            <circle
              cx={px(x1)}
              cy={py(y1)}
              r={4.2}
              className={styles.curveHandle}
            />
            <circle
              cx={px(x2)}
              cy={py(y2)}
              r={4.2}
              className={styles.curveHandle}
            />
          </svg>

          <div className={styles.sliders}>
            {(
              [
                ["x1", x1, 0, 1],
                ["y1", y1, -0.3, 1.3],
                ["x2", x2, 0, 1],
                ["y2", y2, -0.3, 1.3],
              ] as const
            ).map(([name, value, min, max], index) => (
              <label key={name} className={styles.sliderRow}>
                <span className={styles.sliderName}>{name}</span>
                <Slider
                  className={styles.slider}
                  min={min}
                  max={max}
                  step={0.01}
                  value={value}
                  tooltip={{ formatter: (v) => Number(v).toFixed(2) }}
                  onChange={(v) => updatePoint(index, Number(v))}
                />
                <span className={styles.sliderValue}>{value.toFixed(2)}</span>
              </label>
            ))}
          </div>
          <p className={styles.customHint}>
            {t("account.motionCustomControls")}
          </p>
        </div>
      ) : null}

      <div className={styles.preview}>
        <span className={styles.previewLabel}>
          {t("account.motionPreview", "手感预览")}
        </span>
        <div className={styles.track}>
          <span
            className={styles.dot}
            style={{
              animationTimingFunction: tokens.enterEase,
              animationDuration: `${Math.max(600, tokens.duration.slow * 4)}ms`,
            }}
          />
        </div>
      </div>

      {reduced ? (
        <p className={styles.reducedNote}>{t("account.motionReducedOn")}</p>
      ) : null}

      <div className={styles.footer}>
        <span className={styles.localHint}>
          {t("account.motionSaveLocalHint")}
        </span>
        <Button size="small" icon={<RotateCcw size={14} />} onClick={reset}>
          {t("account.motionReset", "恢复默认")}
        </Button>
      </div>
    </div>
  );
}
