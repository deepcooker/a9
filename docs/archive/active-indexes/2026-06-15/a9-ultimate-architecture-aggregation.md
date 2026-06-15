# A9 最高形态架构聚合索引

This file is now a short active index. The full aggregation draft was archived
to:

`docs/archive/2026-06-noise-reduction/a9-ultimate-architecture-aggregation.md`

## Current Conclusion

A9's highest shape is:

```text
Private Agent OS
+ financial trading infrastructure control plane
+ private compute/model scheduling layer
+ 24h worker and monitor runtime
+ evidence/trace/wrongbook production layer for A3B
```

Current engineering priority remains:

```text
P0 requirements/ADR closure for 24h worker + monitor + communication foundation
P1 24h worker + monitor reliability
P2 communication foundation and private node connectivity
P3 A9 core contracts supporting P1/P2
P4 reference/vendor baseline for P1/P2
P5 mobile/control product packet, UI details frozen
P6 compute stage A
P7 NZX technical MVP
```

## Reading Rule

The archived full aggregation is architecture debate evidence, not an
implementation contract. A worker may read a bounded section only when the task
explicitly asks for highest-shape architecture review.

