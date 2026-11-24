import cx from "classnames";

import styles from "./HappyclawSpinner.module.less";

interface HappyclawSpinnerProps {
  /** antd appends `${prefixCls}-dot` when this is the ConfigProvider indicator. */
  className?: string;
}

/**
 * Loading indicator wired globally as the antd Spin indicator: a faint
 * track with a short brand arc and an empty center. The logo splash stays
 * on the first-paint boot screen in index.html.
 */
export default function HappyclawSpinner({ className }: HappyclawSpinnerProps) {
  return (
    <span className={cx(styles.host, className)}>
      <span className={styles.track} />
      <span className={styles.ring} />
    </span>
  );
}
