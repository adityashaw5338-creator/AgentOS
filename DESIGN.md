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
  hover: "#155567"
  selection: "#d5e9ee"
  positiveBackground: "#dcfae5"
  positiveInk: "#04250e"
  negativeBackground: "#ffedea"
  negativeInk: "#831c1e"
  warningBackground: "#fffbeb"
  warningBorder: "#f0dfb4"
  runningBackground: "#e3f1f4"
  neutralInk: "#353736"
  darkGround: "#101112"
  darkSurface: "#191b1c"
  darkRaised: "#212425"
  darkActive: "#2b3031"
  darkBorder: "#343a3b"
  darkControl: "#647174"
  darkText: "#edf3f2"
  darkMuted: "#acb8b7"
  darkAccent: "#79ddd0"
  darkPositive: "#85dbae"
  darkNegative: "#ff9296"
  darkWarning: "#f2c780"
  darkPositiveBackground: "#1c372a"
  darkNegativeBackground: "#40272b"
  darkWarningBackground: "#352f22"
  darkPrimaryHover: "#a0ecdf"
  darkPrimaryInk: "#122725"
  darkSelection: "#325953"
  darkPositiveInk: "#a6eac2"
  darkNegativeInk: "#ffc0c3"
  darkWarningBorder: "#665638"
  darkAccentSoft: "#203c38"
typography:
  title:
    fontFamily: "IBM Plex Sans, system-ui, sans-serif"
    fontSize: "28px"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.03em"
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
  card: "12px"
  control: "8px"
  state: "5px"
spacing:
  gutter: "24px"
  inner: "20px"
  compact: "12px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.surface}"
    rounded: "{rounded.control}"
    padding: "9px 16px"
    height: "40px"
  task-detail:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.card}"
    padding: "28px"
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

## Color themes

The top-bar Dark mode toggle is available before connection and remains visible on phones.
The first paint follows the operating system unless `agentos.theme` stores an explicit
light/dark choice. Only this preference is persisted; tokens and task data stay out of browser
storage. Storage restrictions leave a working toggle with an in-memory preference.
The charcoal theme uses mint actions and data, warm approval states, rose errors, and legible
neutral secondary text. Native inputs, selection, focus, progress, status chips, and browser
theme-color all follow the same theme. Keyboard theme switching is immediate.

## Typography

Title 28px/600; connection heading 32px; composer heading 20px; task goal heading 22px;
section heading 16px/600; body 14px/400; compact controls, step descriptions,
and logs 13px; metadata and code 12px; secondary state labels and task IDs 11px.
The wordmark uses 23px on desktop and 17px on phones; final task results use 34px/500
(30px on phones), and intermediate results awaiting approval use 26px.
Table figures are tabular and results are right-aligned. Touch inputs use 16px text
to avoid browser zoom.

## Layout

24px is the shared layout gutter. Navigation is 228px at desktop; sheet padding is 28px,
20px on tablets, and 16px on phones. At 1200px and above, the composer and saved history
share the left column while the selected plan begins beside the composer on the right.
The composer row sizes to its content even when the plan is much longer. Its compact
header, two example chips, and inline controls keep saved history in the first viewport.
At 1100px navigation moves into a top row. Below 760px task detail becomes a single
region with Back to saved tasks. On phones with saved history, New task expands the
composer so saved rows stay near the top; the first-run composer stays open.

## Elevation & Depth

The frame, sheet, and composer each differ by a single tone step in both themes.
The execution pane uses the sheet surface with a quiet border; result wells carry a pale
accent tint. Resting surfaces have no shadow. Primary actions and meaningful data carry teal
in light mode and mint in dark mode.

## Shapes

Cards use 12px corners, controls 8px, the sheet 16px, and state tags 5px. Buttons
are at least 40px on desktop and 44px on phones. Step numbers sit in 32px circles,
linked by a line that takes the accent after the preceding step completes.

## Components

- Tasks: composer, filtered saved-task list, and selected task detail with plan and log.
- Tool registry: actual registered tools with disclosed Pydantic JSON schemas.
- Connect: token form and the real local server command.
- Connect pairs the token form with a numbered startup guide, including the Windows launcher;
  the guide stacks below the form on phones. A separate three-stage flow explains Plan,
  Validate, and Execute; its short initial animation is instructional, not live task data.
- The composer groups goal entry with a compact native planner selector. Its available-tool
  names come directly from the current registry, with a link to their argument schemas.
- Phones: navigation becomes a top row. Task selection opens the detail as one region;
  Back restores the list and its scroll position. No page-wide horizontal scrolling.
- Authentication tokens remain only in tab memory. Disconnect clears loaded tasks,
  goal text, schemas, status messages, loading indicators, and the token; refreshing the
  browser page requires reconnecting.
- Preview saves a pending plan; Execute runs it. Approve advances one waiting step,
  then execution pauses again where another approval is required.
- The task form uses a native Planner select for Local and optional AI planning. It
  shows the configured model when available and keeps Local usable during setup or
  metadata failures. AI mode explains that the goal and tool schemas go to the configured
  provider and locks approval on for every step. Returning to Local restores its previous
  approval choice. Planner options and selection are cleared on disconnect; delayed
  metadata cannot change a newer connection or replace the operator's chosen mode.
- Delayed responses cannot replace a newer task revision or show an error on another
  selected task. Refreshing saved tasks preserves an open mobile task form and its draft.
- Keyboard focus follows the next approval action; when execution finishes, it moves
  to the task heading. In-flight actions disable the task controls until their result arrives.
- Empty, filtered-empty, offline, rejected-token, failed-task, loading, and stale-revision
  states each provide a concrete recovery action. History starts empty, with no seeded
  demonstration tasks or invented statistics.
- Failed tasks offer Edit goal; zero-step planning failures also offer Edit with Local.
  These actions open the composer without submitting, keep saved history, and preserve a different
  draft already in the form. AI remains selected unless the operator explicitly chooses Local.
- The step waiting for approval has an amber number and state label; the approval explanation
  displays the next tool and its exact saved JSON arguments before the action buttons, including
  prior-result references. The full rail still shows every step and uses `aria-current="step"`.
- The execution summary and native progress bar show completed steps against actual total steps.
  An empty plan has no bar. Final results are more prominent than intermediate results.
  The empty detail pane teaches the workflow without fabricating history or outcomes.
- Successful creation and execution notices remain live announcements but do not repeat visible
  status. Creation notices clear when another task is selected or execution changes its revision.
- Planning shows an indeterminate activity indicator and an explicit provider-wait message.
  Its live region sits outside the busy form. History loading uses the heading's count space,
  keeping existing task rows stationary. Disconnect clears all activity state.
- Motion makes the actual workflow legible. A pointer-created or selected plan reveals steps
  with 190ms opacity/8px translation, staggered 35ms with total motion capped at 260ms. Changes
  to the current step or result animate once per new revision; a routine refresh does not replay
  them. Pointer navigation uses a 200ms continuity transition. Keyboard input, disconnect, and
  reduced-motion changes cancel running effects and invalidate pending pointer effects.
- Pointer presses scale buttons to 0.97 over 160ms with `cubic-bezier(0.23, 1, 0.32, 1)`;
  transitions retarget on interruption. The same curve drives the workflow effects. The initial
  connection guide draws its lines over 650ms with an 180ms offset and introduces its nodes over
  400ms with 100ms offsets. This plays once on arrival; it never delays the token form.
- A 1s linear rotation indicates active planning, never a completion percentage. Reduced motion
  keeps static pressed styling, readable status and all content, with no spatial effects.
  Hover feedback requires a fine pointer with hover. CSS and WAAPI need no animation library.

### Refinement direction

The Framed sheet app direction (seed 1046047228) retains Plex and the cool light identity,
with a matching charcoal theme and a stronger emphasis on the execution pane.
The question remains: what happened in this task, and what needs a decision next? The cool frame
and connected tool-step rail carry the product identity. Production data always comes from the
engine; browser fixtures live only in isolated verification databases.

### Assets

IBM Plex Sans variable and IBM Plex Mono regular fonts are sourced from the Google Fonts
repository, retaining `agent_engine/web/fonts/OFL-IBM-Plex.txt`. The AgentOS mark is an
authored SVG monogram. No stock or generated bitmap assets are used.
