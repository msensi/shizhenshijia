interface BrandMarkProps {
  /** 主尺寸 72（首页品牌区）/ 32（favicon 源图） */
  size?: 72 | 32;
}

/** 品牌图形：方案 A「火眼」（已锁定）。
 *  放大镜精修版：镜内绿勾＝查明为真，镜角红叉＝识破为假。
 *  颜色全部引用 Design Token，描边比例固定，可无损缩放。
 */
export function BrandMark({ size = 72 }: BrandMarkProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 96 96"
      role="img"
      aria-label="是真是假 品牌图形"
      className="shrink-0"
    >
      <circle cx="42" cy="44" r="24" fill="none" stroke="var(--accent)" strokeWidth="5" />
      <line x1="60" y1="62" x2="78" y2="80" stroke="var(--accent)" strokeWidth="6.5" strokeLinecap="round" />
      <path
        d="M31 44.5 L39.5 53 L55 35.5"
        fill="none"
        stroke="var(--status-safe)"
        strokeWidth="5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <g stroke="var(--status-danger)" strokeWidth="4.5" strokeLinecap="round">
        <line x1="70" y1="14" x2="80" y2="24" />
        <line x1="80" y1="14" x2="70" y2="24" />
      </g>
    </svg>
  );
}
