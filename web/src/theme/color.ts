// 색상 계산 헬퍼 (데스크톱 `ui/theme.py`의 `_shade`/`_mix`/`relative_luminance`/
// `contrast_ratio`와 동일한 알고리즘, spec §5.3).

/** `#RRGGBB`의 각 채널을 `factor`배로 어둡게/밝게 만든다. */
export function shade(hex: string, factor: number): string {
  const value = hex.replace("#", "");
  if (value.length !== 6) {
    return hex;
  }
  const channel = (index: number): number =>
    Math.min(255, Math.round(parseInt(value.slice(index, index + 2), 16) * factor));
  return `#${toHex(channel(0))}${toHex(channel(2))}${toHex(channel(4))}`;
}

/** `foreground`를 `ratio` 비율로 `background`에 섞는다. */
export function mix(foreground: string, background: string, ratio: number): string {
  const fg = foreground.replace("#", "");
  const bg = background.replace("#", "");
  if (fg.length !== 6 || bg.length !== 6) {
    return foreground;
  }
  const channel = (index: number): number => {
    const f = parseInt(fg.slice(index, index + 2), 16);
    const b = parseInt(bg.slice(index, index + 2), 16);
    return Math.min(255, Math.round(f * ratio + b * (1 - ratio)));
  };
  return `#${toHex(channel(0))}${toHex(channel(2))}${toHex(channel(4))}`;
}

/** `#RRGGBB` 색상의 WCAG 상대 휘도를 계산한다. */
export function relativeLuminance(hex: string): number {
  const value = hex.replace("#", "");
  if (value.length !== 6) {
    throw new Error("색상은 #RRGGBB 형식이어야 합니다.");
  }
  const channels = [0, 2, 4].map(
    (index) => parseInt(value.slice(index, index + 2), 16) / 255,
  );
  const linear = channels.map((channel) =>
    channel <= 0.04045
      ? channel / 12.92
      : ((channel + 0.055) / 1.055) ** 2.4,
  );
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

/** 두 `#RRGGBB` 색상의 WCAG 대비율을 반환한다. */
export function contrastRatio(foreground: string, background: string): number {
  const [lighter, darker] = [
    relativeLuminance(foreground),
    relativeLuminance(background),
  ].sort((a, b) => b - a);
  return (lighter + 0.05) / (darker + 0.05);
}

function toHex(channel: number): string {
  return channel.toString(16).padStart(2, "0");
}
