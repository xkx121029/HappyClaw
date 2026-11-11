import { useEffect, useState } from "react";

import logoDarkUrl from "./assets/logo_horizontal_dark.png";
import logoWhiteUrl from "./assets/logo_horizontal_white.png";
import { LinuxWindowControls } from "./linux-window-controls";
import { mount } from "./mount";
import "./base.less";
import styles from "./onboarding.module.less";

/**
 * Two-step first-run guide for the single-user build.
 *
 * Nothing here stands between the user and the Dashboard: the main window is
 * already loaded behind this one, both buttons are on screen from the first
 * frame, and either one closes the guide for good. Help → 首次引导 reopens it.
 *
 * 第一步只解释"这台机器上没有账号"并给出数据目录；第二步给出托盘、快捷键和
 * 开机自启。没有第三步，没有进度条式的新手任务。
 */
type Step = 0 | 1;

interface Info {
  dataDirectory: string;
  shortcuts: { showWindow: string; newSession: string };
}

const FALLBACK_SHORTCUTS = {
  showWindow: "Ctrl+Shift+H",
  newSession: "Ctrl+Shift+N",
};

/** Both "开始使用" and "跳过引导" count as seen; Help → 首次引导 still reopens it. */
async function finish(): Promise<void> {
  // Persist before closing: the IPC invoke would be cut off by the window.
  await window.octopDesktop?.clientSettings.set({ onboardingCompleted: true });
  window.close();
}

function StepDots({ step }: { step: Step }) {
  return (
    <span className={styles.dots} aria-hidden="true">
      <span className={step === 0 ? styles.dotActive : styles.dot} />
      <span className={step === 1 ? styles.dotActive : styles.dot} />
    </span>
  );
}

function FirstStep({
  info,
  onNext,
  onSkip,
}: {
  info: Info | null;
  onNext: () => void;
  onSkip: () => void;
}) {
  return (
    <>
      <p className={styles.eyebrow}>第一次使用</p>
      <h1 className={styles.title}>
        这台电脑上
        <br />
        只有你一个人
      </h1>
      <p className={styles.body}>
        HappyClaw 没有成员账号与权限配置。打开就是主界面，对话、密钥与工作区都留在本机。
      </p>

      <div className={styles.dataBlock}>
        <span className={styles.dataLabel}>数据目录</span>
        <code className={styles.dataPath} title={info?.dataDirectory ?? ""}>
          {info?.dataDirectory ?? "正在读取…"}
        </code>
        <button
          type="button"
          className={styles.textButton}
          onClick={() => void window.octopDesktop?.openDataDirectory()}
        >
          打开
        </button>
      </div>

      <div className={styles.footer}>
        <button type="button" className={styles.skip} onClick={onSkip}>
          跳过引导
        </button>
        <div className={styles.footerRight}>
          <StepDots step={0} />
          <button type="button" className={styles.primary} onClick={onNext}>
            下一步
          </button>
        </div>
      </div>
    </>
  );
}

function SecondStep({
  info,
  autoLaunch,
  onAutoLaunch,
  onBack,
  onDone,
}: {
  info: Info | null;
  autoLaunch: boolean;
  onAutoLaunch: (value: boolean) => void;
  onBack: () => void;
  onDone: () => void;
}) {
  const shortcuts = info?.shortcuts ?? FALLBACK_SHORTCUTS;
  return (
    <>
      <p className={styles.eyebrow}>常用操作</p>
      <h1 className={styles.title}>关掉窗口，它还在</h1>
      <p className={styles.body}>
        HappyClaw 常驻托盘：关窗不退出，真正退出请用托盘菜单。下面这些随时都能在帮助菜单里找回。
      </p>

      <dl className={styles.keys}>
        <div className={styles.keyRow}>
          <dt>唤起窗口</dt>
          <dd>
            <kbd className={styles.kbd}>{shortcuts.showWindow}</kbd>
          </dd>
        </div>
        <div className={styles.keyRow}>
          <dt>新建会话</dt>
          <dd>
            <kbd className={styles.kbd}>{shortcuts.newSession}</kbd>
          </dd>
        </div>
        <div className={styles.keyRow}>
          <dt>托盘菜单</dt>
          <dd className={styles.keyNote}>打开窗口 · 立即备份 · 退出</dd>
        </div>
      </dl>

      <button
        type="button"
        role="switch"
        aria-checked={autoLaunch}
        className={styles.switchRow}
        onClick={() => onAutoLaunch(!autoLaunch)}
      >
        <span className={styles.switchCopy}>
          <span className={styles.switchTitle}>登录时自动启动</span>
          <span className={styles.switchHint}>默认关闭，可随时在设置里修改</span>
        </span>
        <span className={autoLaunch ? styles.switchTrackOn : styles.switchTrack}>
          <span className={autoLaunch ? styles.switchThumbOn : styles.switchThumb} />
        </span>
      </button>

      <div className={styles.footer}>
        <button type="button" className={styles.skip} onClick={onBack}>
          上一步
        </button>
        <div className={styles.footerRight}>
          <StepDots step={1} />
          <button type="button" className={styles.primary} onClick={onDone}>
            开始使用
          </button>
        </div>
      </div>
    </>
  );
}

function Onboarding() {
  const [step, setStep] = useState<Step>(0);
  const [info, setInfo] = useState<Info | null>(null);
  const [autoLaunch, setAutoLaunch] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const [desktop, settings] = await Promise.all([
        window.octopDesktop?.desktopInfo(),
        window.octopDesktop?.clientSettings.get(),
      ]);
      if (cancelled) return;
      if (desktop) {
        setInfo({
          dataDirectory: desktop.dataDirectory,
          shortcuts: desktop.shortcuts,
        });
      }
      if (settings) setAutoLaunch(settings.launchAtLogin === true);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") void finish();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const setLaunchAtLogin = (value: boolean) => {
    setAutoLaunch(value);
    void window.octopDesktop?.clientSettings.set({ launchAtLogin: value });
  };

  return (
    <main className={styles.shell}>
      <LinuxWindowControls />
      <header className={styles.top}>
        <img className={`${styles.logo} ${styles.logoLight}`} src={logoDarkUrl} alt="HappyClaw" />
        <img className={`${styles.logo} ${styles.logoDark}`} src={logoWhiteUrl} alt="HappyClaw" />
        <span className={styles.counter}>{step + 1} / 2</span>
      </header>
      <section className={styles.panel} key={step} aria-live="polite">
        {step === 0 ? (
          <FirstStep info={info} onNext={() => setStep(1)} onSkip={() => void finish()} />
        ) : (
          <SecondStep
            info={info}
            autoLaunch={autoLaunch}
            onAutoLaunch={setLaunchAtLogin}
            onBack={() => setStep(0)}
            onDone={() => void finish()}
          />
        )}
      </section>
    </main>
  );
}

mount(<Onboarding />);
