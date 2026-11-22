import { createGlobalStyle } from "antd-style";
import { ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import enUS from "antd/locale/en_US";
import dayjs from "dayjs";
import "dayjs/locale/zh-cn";
import { lazy, Suspense, useEffect } from "react";
import {
  DesktopChromeProvider,
  useDesktopChrome,
} from "./hooks/useDesktopChrome";
import { useNativeWindowChrome } from "./hooks/useNativeWindowChrome";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { routerBasename } from "./utils/publicUrl";
import { useTranslation } from "react-i18next";
import MainLayout from "./layouts/MainLayout";
import SetupPage from "./pages/Setup";
import AuthGuard from "./components/AuthGuard";
import PwaUpdatePrompt from "./components/PwaUpdatePrompt";
import DesktopWindowDragBand from "./components/DesktopWindowDragBand";
import WindowsAppMenu from "./components/WindowsAppMenu";
import OctopSpinner from "./components/OctopSpinner";
import { AntdAppProvider } from "./components/AntdAppProvider";
import { popupLayer } from "./utils/overlayLayers";
import GlobalErrorBoundary from "./components/ErrorBoundary";
import { ThemeProvider, useTheme } from "./context/ThemeContext";
import { MotionProvider, useMotionTokens } from "./motion/MotionProvider";
import { AgentProvider } from "./context/AgentContext";
import { LayoutModeProvider } from "./context/LayoutModeContext";
import { VoiceOutputProvider } from "./context/VoiceOutputContext";
import { useIsMobile } from "./hooks/useIsMobile";
import { antdThemeConfig } from "./styles/tokens/antd";
import { antdOverrides } from "./styles/appearance/derive";
import { useAppearance } from "./styles/appearance/useAppearance";
import "./styles/theme-vars.css";
import "./styles/layout.css";
import "./styles/form-override.css";
import "./styles/spin-override.css";
import "./motion/motion.css";

// Mobile gets its own shell and page tree. The chunk is only requested when a
// phone-sized viewport is detected, so desktop first paint is unaffected.
const MobileRoutes = lazy(() =>
  import("./mobile/MobileRoutes").then((m) => ({ default: m.MobileRoutes })),
);

const GlobalStyle = createGlobalStyle`
* {
  margin: 0;
  box-sizing: border-box;
}
`;

function ThemedApp() {
  const { isDark, palette, customColor } = useTheme();
  const motion = useMotionTokens();
  const { t, i18n } = useTranslation();
  const isMobile = useIsMobile();
  const desktopChrome = useDesktopChrome();
  // Native window buttons follow the app theme. Linux draws square ones.
  useNativeWindowChrome();
  // Make antd built-ins (Popconfirm OK/Cancel, Modal default footer, Empty,
  // Pagination, DatePicker, Table… ) follow the current UI language.
  // DatePicker month/weekday labels come from dayjs — keep it in sync too.
  const isZh = i18n.language?.toLowerCase().startsWith("zh") ?? false;
  const antdLocale = isZh ? zhCN : enUS;
  dayjs.locale(isZh ? "zh-cn" : "en");

  // Set document title based on current language
  useEffect(() => {
    document.title = t("app.pageTitle");
  }, [t]);

  // One type/space/radius/motion scale for every antd surface. Values come
  // from the shared token tables so the CSS custom properties and antd can
  // never drift apart again.
  const appearance = useAppearance();
  const themeConfig = antdThemeConfig({
    isDark,
    isMobile,
    palette,
    customColor,
    motion: {
      reduced: motion.reduced,
      fast: motion.duration.fast,
      base: motion.duration.base,
      slow: motion.duration.slow,
      enterEase: motion.enterEase,
    },
  });

  // Appearance overrides ride on top of the shared tokens: radius, density,
  // font size and font family, all derived from one settings object.
  const appearanceOverrides = antdOverrides(appearance);
  const mergedTheme: typeof themeConfig = {
    ...themeConfig,
    token: { ...themeConfig.token, ...appearanceOverrides.token },
    components: { ...themeConfig.components, ...appearanceOverrides.components },
  };

  return (
    <ConfigProvider
      theme={mergedTheme}
      prefixCls="octop"
      locale={antdLocale}
      getPopupContainer={popupLayer}
      spin={{ indicator: <OctopSpinner /> }}
    >
      <AntdAppProvider>
        <DesktopChromeProvider value={desktopChrome}>
          <PwaUpdatePrompt />
          {/* 单人本机模式：登录 / 邀请入口已移除，旧书签直接回主页。
              首次使用的服务端初始化向导仍保留在 /setup。 */}
          <DesktopWindowDragBand />
          <WindowsAppMenu />
          <Routes>
            <Route path="/login" element={<Navigate to="/chat" replace />} />
            <Route path="/login/*" element={<Navigate to="/chat" replace />} />
            <Route path="/invite" element={<Navigate to="/chat" replace />} />
            <Route path="/setup" element={<SetupPage />} />
            <Route
              path="/*"
              element={
                <AuthGuard>
                  <AgentProvider>
                    <LayoutModeProvider>
                      <VoiceOutputProvider>
                        {isMobile ? (
                          <Suspense fallback={null}>
                            <MobileRoutes />
                          </Suspense>
                        ) : (
                          <MainLayout />
                        )}
                      </VoiceOutputProvider>
                    </LayoutModeProvider>
                  </AgentProvider>
                </AuthGuard>
              }
            />
          </Routes>
        </DesktopChromeProvider>
      </AntdAppProvider>
    </ConfigProvider>
  );
}

function App() {
  return (
    // `useTransitions` off: with router transitions on, React keeps the old
    // page mounted while a lazy route chunk downloads and never renders the
    // Suspense fallback, so a nav click looks like it did nothing.
    <BrowserRouter basename={routerBasename()} useTransitions={false}>
      <GlobalErrorBoundary>
        <GlobalStyle />
        <ThemeProvider>
          <MotionProvider>
            <ThemedApp />
          </MotionProvider>
        </ThemeProvider>
      </GlobalErrorBoundary>
    </BrowserRouter>
  );
}

export default App;
