# Sites integration handoff

This directory contains the shared hosted v2 wire validator and server-side relay. The complete Q3HASH Lab remains in its own Sites source repository. The Site patch applies against the exact existing source revision `87586ffe7af04be6691890ed3d2a70fc62e3afc2`. This preserves the existing routing, storage, playground and browser Pyodide tool.

The patched checkout must have byte-identical copies of `research-bridge.ts` and `research-contract.ts` in its `lib/`. To verify the complete checkout from the Site root, use the pinned pnpm version and run:

```sh
pnpm install --frozen-lockfile
pnpm typecheck
pnpm test
pnpm build
pnpm audit --prod
```

The GitHub workflow checks fresh authentic Python fixtures with the exact shared TypeScript validator and relay, then type-checks and bundles the two modules. The full Site requires its separate checkout and lockfile. The Site patch also contains the managed identity route, D1 quotas, console, dependency changes and workerd tests.

ChatGPT Sites owns sign-in, sign-out and callback navigation. Site API handlers consume only the platform request context for identity. A non-safelisted request header and same-origin checks protect the relay. Service authentication uses a separate Render bearer stored only in server settings. Application checks locally prove the relay behaviour with test identities, while spoofing resistance, session replay and real sign-in need the deployed Sites ingress acceptance tests.
