# Mobile Control Source

> Date: 2026-06-05
> Status: canonical source routing

## Canonical Mobile Workspace

The active A9 mobile/control workspace is:

```text
/mnt/d/root/a9_mobile_agent_lab
```

Windows path:

```text
D:\root\a9_mobile_agent_lab
```

Do not use `/mnt/d/root/a9_mobile` as the active mobile implementation target
unless a newer human decision explicitly promotes it again.

## Why

The project originally identified `/mnt/d/root/a9_mobile` as the Expo mobile
base. Later, the Agent OS/GPT-like control surface moved into a same-level lab
copy so the trading workspace could be preserved while the Agent tab, monitor
control, communication recovery, and GPT-like drawer were iterated.

The current running Expo web service on port `8199` is started from
`/mnt/d/root/a9_mobile_agent_lab`.

## Governance

`/mnt/d/root/a9_mobile_agent_lab` is now an independent Git repository.

Initial baseline commit:

```text
dd4a4f2 Initial A9 mobile agent lab baseline
```

Ignored runtime/build folders include:

```text
node_modules/
.expo/
dist/
web-build/
```

Future mobile work must use normal Git discipline in this workspace:

- inspect local status before editing
- keep changes scoped to the requested mobile slice
- run `npx tsc --noEmit`
- run `npm run smoke:mobile` when the Agent OS shell, drawer, composer, or
  control cards are touched
- keep the Expo web service on `8199` aligned with this workspace

## Current Role

Mobile is the operator control plane, not the core runtime architecture.

Allowed current work:

- expose runtime/monitor/communication state already provided by A9 APIs
- submit bounded commands through the control API
- make risky queue/task quality visible to the operator
- verify the GPT-like Agent OS shell remains usable

Frozen unless a task contract says otherwise:

- broad visual polish
- trading business UI redesign
- NZX business implementation
- replacing the mobile app architecture
