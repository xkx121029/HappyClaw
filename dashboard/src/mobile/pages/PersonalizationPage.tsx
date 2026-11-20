import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import cx from "classnames";

import { preferencesApi } from "../../api/modules/preferences";
import { updateApi } from "../../api/modules/update";
import { useAgent } from "../../context/AgentContext";
import { useTheme, type ThemePreference } from "../../context/ThemeContext";
import {
  PALETTE_SWATCH,
  VALID_PALETTES,
  type ThemePalette,
} from "../../styles/themePalettes";
import { applyUserLocale } from "../../utils/locale";
import { MobileAvatar } from "../components/MobileAvatar";
import { MobileListRow } from "../components/MobileListRow";
import { MobilePage } from "../components/MobilePage";
import { MobileSegmented } from "../components/MobileSegmented";
import { showMobileToast } from "../components/MobileToast";

type SwatchPalette = Exclude<ThemePalette, "custom">;

export function PersonalizationPage() {
  const navigate = useNavigate();
  const { t, i18n } = useTranslation();
  const { preference, setPreference, palette, setPalette } = useTheme();
  const { activeAgent } = useAgent();
  const [version, setVersion] = useState<string | null>(null);
  const [savingLocale, setSavingLocale] = useState(false);

  const appearanceOptions = useMemo<
    Array<{ value: ThemePreference; label: string }>
  >(
    () => [
      {
        value: "system",
        label: t("mobile.personalization.followSystem", "跟随系统"),
      },
      { value: "light", label: t("mobile.personalization.light", "浅色") },
      { value: "dark", label: t("mobile.personalization.dark", "深色") },
    ],
    [t],
  );

  const languageOptions = useMemo<Array<{ value: "zh" | "en"; label: string }>>(
    () => [
      { value: "zh", label: "简体中文" },
      { value: "en", label: "English" },
    ],
    [],
  );

  const paletteLabel = useMemo<Record<SwatchPalette, string>>(
    () => ({
      rose: t("mobile.personalization.paletteRose", "玫瑰"),
      tech: t("mobile.personalization.paletteTech", "科技蓝"),
      indigo: t("mobile.personalization.paletteIndigo", "靛青"),
      teal: t("mobile.personalization.paletteTeal", "青绿"),
      violet: t("mobile.personalization.paletteViolet", "紫罗兰"),
      emerald: t("mobile.personalization.paletteEmerald", "翡翠"),
      amber: t("mobile.personalization.paletteAmber", "琥珀"),
      slate: t("mobile.personalization.paletteSlate", "石板灰"),
    }),
    [t],
  );

  const locale: "zh" | "en" = i18n.language?.toLowerCase().startsWith("zh")
    ? "zh"
    : "en";

  useEffect(() => {
    let alive = true;
    updateApi
      .getUpdateStatus()
      .then((status) => {
        if (alive) setVersion(status.current_version);
      })
      .catch(() => {
        /* 版本号属于锦上添花，取不到就不展示 */
      });
    return () => {
      alive = false;
    };
  }, []);

  const changeLocale = async (next: string) => {
    if (next === locale || savingLocale) return;
    setSavingLocale(true);
    try {
      const prefs = await preferencesApi.setLocale(next);
      await applyUserLocale(prefs.locale);
      showMobileToast(
        next === "zh"
          ? t("mobile.personalization.switchedZh", "已切换为简体中文")
          : t(
              "mobile.personalization.switchedEn",
              "Language switched to English",
            ),
      );
    } catch {
      showMobileToast(
        t("mobile.personalization.saveFailed", "语言保存失败，请稍后再试"),
      );
    } finally {
      setSavingLocale(false);
    }
  };

  return (
    <MobilePage title={t("mobile.personalization.title", "个性化")} back>
      <div className="m-section">
        <div className="m-section-head">
          <div className="m-section-title">
            {t("mobile.personalization.appearance", "外观")}
          </div>
        </div>
        <MobileSegmented
          options={appearanceOptions}
          value={preference}
          onChange={setPreference}
        />

        <div className="m-mt16">
          <div className="m-field-label" style={{ marginBottom: 10 }}>
            {t("mobile.personalization.themeColor", "主题色")}
          </div>
          <div className="m-pillrow">
            {VALID_PALETTES.map((item) => (
              <button
                key={item}
                type="button"
                aria-label={paletteLabel[item as SwatchPalette]}
                aria-pressed={palette === item}
                className={cx("m-swatch", palette === item && "is-active")}
                style={{ background: PALETTE_SWATCH[item] }}
                onClick={() => setPalette(item)}
              />
            ))}
          </div>
          {palette === "custom" ? (
            <div className="m-field-hint">
              {t(
                "mobile.personalization.customHint",
                "当前使用自定义品牌色，可在桌面端重新挑选。",
              )}
            </div>
          ) : null}
        </div>
      </div>

      <div className="m-section">
        <div className="m-section-head">
          <div className="m-section-title">
            {t("mobile.personalization.language", "语言")}
          </div>
        </div>
        <MobileSegmented
          options={languageOptions}
          value={locale}
          onChange={(next) => void changeLocale(next)}
        />
        <div className="m-field-hint" style={{ marginTop: 10 }}>
          {t(
            "mobile.personalization.languageHint",
            "界面文案与后端回复会一起切换。",
          )}
        </div>
      </div>

      <div className="m-section">
        <div className="m-section-head">
          <div className="m-section-title">
            {t("mobile.personalization.defaultExpert", "默认专家")}
          </div>
        </div>
        <div className="m-group">
          <MobileListRow
            iconNode={
              <MobileAvatar
                name={activeAgent?.name ?? "?"}
                src={activeAgent?.icon_url}
                color={activeAgent?.color}
                size={34}
                square
              />
            }
            title={
              activeAgent?.name ??
              t("mobile.personalization.chooseExpert", "选择专家")
            }
            subtitle={t(
              "mobile.personalization.defaultExpertSub",
              "首页问候、默认对话与快速对话都跟随这个选择",
            )}
            chevron
            onClick={() => navigate("/m/experts")}
          />
        </div>
      </div>

      <div className="m-section">
        <div className="m-section-head">
          <div className="m-section-title">
            {t("mobile.personalization.bao", "宝")}
          </div>
        </div>
        <div className="m-group">
          <MobileListRow
            icon="bao"
            title={t("mobile.personalization.baoAppearance", "宝的外观")}
            subtitle={t(
              "mobile.personalization.baoAppearanceSub",
              "外形、身体色、眼睛色与名字，全站共用同一份配置",
            )}
            chevron
            onClick={() => navigate("/m/bao")}
          />
        </div>
      </div>

      <div className="m-section">
        <div className="m-section-head">
          <div className="m-section-title">
            {t("mobile.personalization.about", "关于")}
          </div>
        </div>
        <div className="m-group">
          <MobileListRow
            title={t("mobile.personalization.app", "应用")}
            meta="HAPPYCLAW"
          />
          <MobileListRow
            title={t("mobile.personalization.version", "版本")}
            meta={version ?? "—"}
            subtitle={
              version
                ? t(
                    "mobile.personalization.versionSynced",
                    "手机端界面与桌面端同源",
                  )
                : t(
                    "mobile.personalization.versionUnknown",
                    "暂时无法获取版本信息",
                  )
            }
          />
        </div>
      </div>
    </MobilePage>
  );
}
