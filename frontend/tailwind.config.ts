import type { Config } from 'tailwindcss';

/**
 * Tailwind 主题与 src/styles/tokens.css 的 CSS 变量一一映射。
 * 组件内只允许使用这些语义化类名，禁止裸 hex。
 */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: 'var(--bg)',
        surface: 'var(--surface)',
        'surface-warm': 'var(--surface-warm)',
        fg: 'var(--fg)',
        'fg-2': 'var(--fg-2)',
        muted: 'var(--muted)',
        meta: 'var(--meta)',
        border: 'var(--border)',
        'border-soft': 'var(--border-soft)',
        accent: {
          DEFAULT: 'var(--accent)',
          on: 'var(--accent-on)',
          hover: 'var(--accent-hover)',
          active: 'var(--accent-active)',
          soft: 'var(--accent-soft)',
        },
        status: {
          safe: 'var(--status-safe)',
          'safe-bg': 'var(--status-safe-bg)',
          danger: 'var(--status-danger)',
          'danger-bg': 'var(--status-danger-bg)',
          dispute: 'var(--status-dispute)',
          'dispute-bg': 'var(--status-dispute-bg)',
          unknown: 'var(--status-unknown)',
          'unknown-bg': 'var(--status-unknown-bg)',
          visual: 'var(--status-visual)',
          'visual-bg': 'var(--status-visual-bg)',
          scope: 'var(--status-scope)',
          'scope-bg': 'var(--status-scope-bg)',
          unclear: 'var(--status-unclear)',
          'unclear-bg': 'var(--status-unclear-bg)',
        },
      },
      fontSize: {
        xs: 'var(--text-xs)',
        sm: 'var(--text-sm)',
        base: 'var(--text-base)',
        lg: 'var(--text-lg)',
        xl: 'var(--text-xl)',
        '2xl': 'var(--text-2xl)',
        '3xl': 'var(--text-3xl)',
      },
      lineHeight: {
        body: 'var(--leading-body)',
        title: 'var(--leading-title)',
        verdict: 'var(--leading-verdict)',
      },
      fontFamily: {
        sans: 'var(--font-display)',
        mono: 'var(--font-mono)',
      },
      borderRadius: {
        sm: 'var(--radius-sm)',
        md: 'var(--radius-md)',
        lg: 'var(--radius-lg)',
        pill: 'var(--radius-pill)',
      },
      boxShadow: {
        ring: 'var(--elev-ring)',
        raised: 'var(--elev-raised)',
      },
      maxWidth: {
        container: 'var(--container-max)',
      },
      minHeight: {
        'touch-min': 'var(--touch-min)',
        'touch-primary': 'var(--touch-primary)',
      },
      transitionDuration: {
        fast: 'var(--motion-fast)',
        base: 'var(--motion-base)',
      },
      transitionTimingFunction: {
        standard: 'var(--ease-standard)',
      },
    },
  },
  plugins: [],
} satisfies Config;
