# A9 Current Mainline

> Date: 2026-06-04
> Status: canonical current mainline

## One Sentence

A9's current engineering mainline is to make the `24h worker + monitor +
communication foundation` stable and governable. The financial AgentOS
architecture is the target environment, but the first execution focus is not
mobile UI, NZX business code, compute RWA, or broad workspace refactor.

## Why

The project has already proved many pieces in MVP form:

- supervisor / auto-next / run evidence
- session refresh and close-reading
- patch apply / guard / scope discipline
- Redis Streams gateway prototype
- control API and early mobile/control surface
- reference project pool and copying discipline

The remaining problem is not lack of ideas. The problem is making the execution
machine and monitor loop reliable enough that later 1000+ implementation tasks
can run without drifting.

## Current Priority

```text
0. Requirements debate and method closure
1. 24h worker + monitor logic
2. Communication foundation and private node/base connectivity
3. A9 core contracts that support 1 and 2
4. Reference/vendor baseline only where needed by 1 and 2
5. Mobile/control product packet, without changing page details now
6. Compute Stage A
7. NZX technical MVP
```

The GPT decision package remains useful, but it must be interpreted through this
current priority. Its `P0 Architecture Decision Packet` should first close the
runtime/monitor/communication execution path, not authorize full product
implementation.

## Non-Negotiable Method

Requirements work is not a formality. Before a worker executes a large slice,
the task must have:

```text
problem
goal
business/data model
state flow
failure/exception flow
reference mechanisms
scope
out_of_scope
acceptance
evidence path
plan revision
```

Business/data first, performance second:

- Data model means real objects, fields, state, authority source, audit, and
  permissions.
- Performance means latency, throughput, reliability, recovery, cost, and
  pressure testing.

If these are unclear, the route is `debate_next`, not `execution_next`.

## Page Freeze

Mobile/web page details are frozen for now. Do not spend worker cycles on GPT
mobile visual polish, drawer behavior, or trading workspace UI unless a newer
task contract explicitly changes this.

Mobile remains important as a future control plane, but current work should
improve the underlying control/session/run/communication foundations first.

The active mobile/control workspace is `/mnt/d/root/a9_mobile_agent_lab`, not
`/mnt/d/root/a9_mobile`. It is now an independent Git repository. Mobile work
is allowed only when it exposes already-defined runtime/monitor/communication
state or bounded control actions; it must not become a broad UI redesign.

## Next Decision Packet Should Answer

1. What exactly must `24h worker + monitor` guarantee before we trust it with
   long execution?
2. What must the monitor see: intent, prompt, bounded context, reference scan,
   diff, tests, evidence, session link, token/context pressure, and intervention
   history?
3. What is the communication model between operator, gateway, worker, node,
   Redis/MySQL, and future mobile client?
4. Which current Python/Rust MVP pieces are kept, wrapped, renamed, or archived?
5. Which reference mechanisms are needed immediately for runtime/monitor and
   communication stability?
6. What is the first small `execution_next` that can run under monitor without
   changing pages or starting NZX code?
