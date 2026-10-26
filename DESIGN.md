---
name: AgentOS
description: A local workspace for inspecting controlled tool workflows.
colors:
  ground: "#f3f7f8"
  surface: "#ffffff"
  raised: "#f4f6f8"
  active: "#ebedee"
  text: "#131416"
  muted: "#5d5f60"
  accent: "#1b6c80"
  positive: "#1e7b4f"
  negative: "#c4242a"
  warning: "#92400e"
  border: "#e8eaec"
  rule: "#f0f1f2"
  control: "#cdced1"
typography:
  title:
    fontFamily: "IBM Plex Sans, system-ui, sans-serif"
    fontSize: "22px"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "-0.02em"
  section:
    fontFamily: "IBM Plex Sans, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 600
    lineHeight: 1.4
  body:
    fontFamily: "IBM Plex Sans, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
  code:
    fontFamily: "IBM Plex Mono, ui-monospace, monospace"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.6
rounded:
  sheet: "16px"
  card: "8px"
  control: "6px"
  state: "4px"
spacing:
  gutter: "24px"
  inner: "20px"
  compact: "12px"
components:
  button-primary:
    backgroundColor: "{colors.text}"
    textColor: "{colors.surface}"
    rounded: "{rounded.control}"
    padding: "7px 14px"
    height: "36px"
  task-detail:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.text}"
    rounded: "{rounded.card}"
    padding: "20px"
---

# AgentOS interface

<!-- impeccable:design-schema 1 -->

The dashboard is an Operate surface: create a tool workflow, inspect its execution, and
make the next approval decision. Real task state drives every count, result, and log.

## Overview

The cool, low-chroma frame surrounds a white work
sheet inset 8px with a 16px radius and a hairline edge. No resting shadows.
The type system is IBM Plex Sans with IBM Plex Mono restricted to tool names, IDs,
schemas, and example code. Both fonts are self-hosted under the SIL Open Font License.

The visual direction is technical standards notation. Its signature is a numbered,
connected step rail beside actual tool calls: it encodes sequence and completion,
rather than decorating the interface. Navigation, buttons, fields, lists, and disclosure
controls follow familiar interface patterns.

## Colors

| Token | Value | Job |
| --- | --- | --- |
| ground | #f3f7f8 | Low-chroma cool frame |
| surface | #ffffff | Main sheet and inputs |
| raised | #f4f6f8 | Task detail and schema surfaces |
| active | #ebedee | Selected navigation and task rows |
| text | #131416 | Primary copy and main action |
| muted | #5d5f60 | Secondary text and placeholders |
| accent | #1b6c80 | Brand mark, selected tab, actual results and completed steps |
| positive | #1e7b4f | Engine health |
| negative | #c4242a | Errors |
| warning | #92400e | Approval instructions |
| border | #e8eaec | Surface edges |
| rule | #f0f1f2 | Row separators |
| control | #cdced1 | Input outlines and step connectors |

## Typography

Title 22px/600; section heading 16px/600; body 14px/400; metadata and code 12px.
Table figures are tabular and results are right-aligned. Touch inputs use 16px text
to avoid browser zoom.

## Layout

24px is the shared layout gutter. Navigation is 228px at desktop; sheet padding is 24px.
At 1100px navigation moves into a top row. Below 760px task detail becomes a single
region with Back to saved tasks. On phones with saved history, New task expands the
composer so saved rows stay near the top; the first-run composer stays open.

## Elevation & Depth

The cool frame, white sheet, and pale task detail each differ by a single tone step.
Resting surfaces have no shadow. Sheet and composer edges are 1px hairlines.

## Shapes

Cards use 8px corners, controls 6px, the sheet 16px, and state tags 4px. Form controls
are at least 36px on desktop and 44px on phones.

## Components

- Tasks: composer, filtered saved-task list, and selected task detail with plan and log.
- Tool registry: actual registered tools with disclosed Pydantic JSON schemas.
- Connect: token form and the real local server command.
- Phones: navigation becomes a top row. Task selection opens the detail as one region;
  Back restores the list and its scroll position. No page-wide horizontal scrolling.
- Authentication tokens remain only in tab memory. Disconnect clears loaded tasks,
  goal text, schemas, status messages, loading indicators, and the token; refreshing the
  browser page requires reconnecting.
- Preview saves a pending plan; Execute runs it. Approve advances one waiting step,
  then execution pauses again where another approval is required.
- Delayed responses cannot replace a newer task revision or show an error on another
  selected task. Refreshing saved tasks preserves an open mobile task form and its draft.
- Keyboard focus follows the next approval action; when execution finishes, it moves
  to the task heading. In-flight actions disable the task controls until their result arrives.
- Empty, filtered-empty, offline, rejected-token, failed-task, loading, and stale-revision
  states each provide a concrete recovery action. History starts empty, with no seeded
  demonstration tasks or invented statistics.
- Motion is limited to 120ms button/navigation feedback and disabled under reduced
  motion. Nothing performs an entrance.

### Assets

IBM Plex Sans variable and IBM Plex Mono regular fonts are sourced from the Google Fonts
repository, retaining `agent_engine/web/fonts/OFL-IBM-Plex.txt`. The AgentOS mark is an
authored SVG monogram. No stock or generated bitmap assets are used.
