# Design System（§20）

tokens：`frontend/src/design/tokens.ts`（CSS 变量注入 `main.tsx`）。

| Token | 值 |
|---|---|
| background | #F7F8FA |
| surface | #FFFFFF |
| border | #D9DEE7 |
| text | #1F2937 |
| muted | #667085 |
| primary | #2C4A6E（slate-navy） |
| success / warning / blocked / info | #3D7A4E / #9A6A0B / #A0453E / #44587A |

组件：`Card` `Badge` `Stepper` `Collapse` `Drawer` `EmptyState` `StatusText`。
规则：无 hero header；ID 用 monospace，正文 sans；radius 6-8px；高密度但分层。
