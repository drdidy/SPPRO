import type { Variants } from "framer-motion";

export const motionTokens = {
  ease: {
    enter: [0.16, 1, 0.3, 1] as [number, number, number, number],
    exit: [0.7, 0, 0.84, 0] as [number, number, number, number],
    snap: [0.2, 0.9, 0.2, 1] as [number, number, number, number],
    risk: [0.34, 1.56, 0.64, 1] as [number, number, number, number]
  },
  duration: {
    xs: 0.12,
    sm: 0.18,
    md: 0.28,
    lg: 0.42,
    xl: 0.72
  },
  stagger: {
    tight: 0.035,
    normal: 0.06,
    panel: 0.09
  }
};

export const shellVariants: Variants = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: {
      duration: motionTokens.duration.sm,
      ease: motionTokens.ease.enter,
      when: "beforeChildren",
      staggerChildren: motionTokens.stagger.panel
    }
  }
};

export const panelVariants: Variants = {
  hidden: { opacity: 0, y: 14, scale: 0.985, filter: "blur(8px)" },
  show: {
    opacity: 1,
    y: 0,
    scale: 1,
    filter: "blur(0px)",
    transition: { duration: motionTokens.duration.lg, ease: motionTokens.ease.enter }
  }
};

export const commandBackdropVariants: Variants = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { duration: motionTokens.duration.xs } },
  exit: { opacity: 0, transition: { duration: motionTokens.duration.xs } }
};

export const commandPanelVariants: Variants = {
  hidden: { opacity: 0, y: -18, scale: 0.975, filter: "blur(8px)" },
  show: {
    opacity: 1,
    y: 0,
    scale: 1,
    filter: "blur(0px)",
    transition: { duration: motionTokens.duration.md, ease: motionTokens.ease.enter }
  },
  exit: {
    opacity: 0,
    y: -10,
    scale: 0.985,
    filter: "blur(6px)",
    transition: { duration: motionTokens.duration.sm, ease: motionTokens.ease.exit }
  }
};
