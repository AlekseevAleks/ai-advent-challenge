// Иконки (inline-SVG, без внешних библиотек).
import type { ReactNode } from 'react';

interface IconProps {
  size?: number;
}

function Svg({ size = 16, children }: IconProps & { children: ReactNode }): ReactNode {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

export function IconDashboard(props: IconProps): ReactNode {
  return (
    <Svg {...props}>
      <rect x="1.5" y="1.5" width="5.5" height="5.5" rx="1.2" />
      <rect x="9" y="1.5" width="5.5" height="5.5" rx="1.2" />
      <rect x="1.5" y="9" width="5.5" height="5.5" rx="1.2" />
      <rect x="9" y="9" width="5.5" height="5.5" rx="1.2" />
    </Svg>
  );
}

export function IconPlug(props: IconProps): ReactNode {
  return (
    <Svg {...props}>
      <path d="M8 1v3M4.5 4h7v3a3.5 3.5 0 0 1-7 0z" />
      <path d="M6.5 10.3V15M9.5 10.3V15" />
    </Svg>
  );
}

export function IconList(props: IconProps): ReactNode {
  return (
    <Svg {...props}>
      <path d="M2 3.5h12M2 8h12M2 12.5h12" />
      <circle cx="2" cy="3.5" r="0.5" />
    </Svg>
  );
}

export function IconGear(props: IconProps): ReactNode {
  return (
    <Svg {...props}>
      <circle cx="8" cy="8" r="2.2" />
      <path d="M8 1.8v2M8 12.2v2M1.8 8h2M12.2 8h2M3.6 3.6l1.4 1.4M11 11l1.4 1.4M12.4 3.6L11 5M5 11l-1.4 1.4" />
    </Svg>
  );
}

export function IconMenu(props: IconProps): ReactNode {
  return (
    <Svg {...props}>
      <path d="M2 4h12M2 8h12M2 12h12" />
    </Svg>
  );
}

export function IconClose(props: IconProps): ReactNode {
  return (
    <Svg {...props}>
      <path d="M4 4l8 8M12 4l-8 8" />
    </Svg>
  );
}

export function IconCopy(props: IconProps): ReactNode {
  return (
    <Svg {...props}>
      <rect x="5.5" y="5.5" width="8" height="8" rx="1.2" />
      <path d="M10.5 2.5h-6A2 2 0 0 0 2.5 4.5v6" />
    </Svg>
  );
}

export function IconCheck(props: IconProps): ReactNode {
  return (
    <Svg {...props}>
      <path d="M3 8.5l3.2 3.2L13 4.5" />
    </Svg>
  );
}

export function IconRefresh(props: IconProps): ReactNode {
  return (
    <Svg {...props}>
      <path d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9M13.5 1.5v3h-3" />
    </Svg>
  );
}

export function IconSun(props: IconProps): ReactNode {
  return (
    <Svg {...props}>
      <circle cx="8" cy="8" r="2.6" />
      <path d="M8 1v2M8 13v2M1 8h2M13 8h2M3.1 3.1l1.4 1.4M11.5 11.5l1.4 1.4M12.9 3.1l-1.4 1.4M4.5 11.5l-1.4 1.4" />
    </Svg>
  );
}

export function IconMoon(props: IconProps): ReactNode {
  return (
    <Svg {...props}>
      <path d="M13.5 9.2A5.8 5.8 0 0 1 6.8 2.5 5.8 5.8 0 1 0 13.5 9.2z" />
    </Svg>
  );
}

export function IconTrash(props: IconProps): ReactNode {
  return (
    <Svg {...props}>
      <path d="M2.5 4h11M6.5 2h3M4 4l.6 9a1.5 1.5 0 0 0 1.5 1.4h3.8a1.5 1.5 0 0 0 1.5-1.4L12 4M6.5 6.5v5M9.5 6.5v5" />
    </Svg>
  );
}

export function IconSearch(props: IconProps): ReactNode {
  return (
    <Svg {...props}>
      <circle cx="7" cy="7" r="4.5" />
      <path d="M10.5 10.5L14 14" />
    </Svg>
  );
}

export function IconArrowLeft(props: IconProps): ReactNode {
  return (
    <Svg {...props}>
      <path d="M10 2.5L4.5 8l5.5 5.5" />
    </Svg>
  );
}

export function IconClock(props: IconProps): ReactNode {
  return (
    <Svg {...props}>
      <circle cx="8" cy="8" r="5.8" />
      <path d="M8 4.5V8l2.5 1.5" />
    </Svg>
  );
}

export function LogoMark(props: IconProps): ReactNode {
  return (
    <svg
      width={props.size ?? 20}
      height={props.size ?? 20}
      viewBox="0 0 20 20"
      fill="none"
      stroke="var(--accent)"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M9.5 18L18 3H6.5L14.5 18H9.5z" />
      <path d="M9 9H3l4 4.5H4.5" />
    </svg>
  );
}