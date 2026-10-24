# Frontend (Vite+)

React + TypeScript on [Vite+](https://viteplus.dev) (`vite-plus@1.4.0`, Bun `1.4.4`).

```bash
bun install
bun run dev      # vp dev (API proxied to :8000)
bun run check    # fmt + lint
bun run build    # tsc -b && vp build
```

Config lives in `vite.config.ts` (lint/fmt via Oxlint/Oxfmt bundled in Vite+).
