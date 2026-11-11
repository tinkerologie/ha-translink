import { css } from "lit";
export const cardStyles = css`
  :host {
    display: block;
    min-width: 0;
    container-type: inline-size;
    color: var(--primary-text-color);
  }
  * {
    box-sizing: border-box;
  }
  ha-card {
    overflow: hidden;
    height: 100%;
    background: var(--ha-card-background, var(--card-background-color));
    border-radius: var(
      --ha-card-border-radius,
      var(--ha-border-radius-lg, 12px)
    );
    font-family: var(--ha-font-family-body, inherit);
  }
  header {
    display: flex;
    align-items: center;
    gap: var(--ha-space-3, 12px);
    padding: var(--ha-space-5, 20px) var(--ha-space-5, 20px)
      var(--ha-space-3, 12px);
  }
  header > .icon {
    display: grid;
    place-items: center;
    width: 44px;
    height: 44px;
    flex-shrink: 0;
    border-radius: var(--ha-border-radius-circle, 50%);
    color: var(--ha-color-on-primary-normal, var(--primary-color));
    background: var(
      --ha-color-fill-primary-quiet-resting,
      var(--secondary-background-color)
    );
  }
  .headings {
    min-width: 0;
    flex: 1;
  }
  h2 {
    margin: 0;
    font-size: var(--ha-font-size-xl, 20px);
    font-weight: var(--ha-font-weight-medium, 500);
    line-height: 1.4;
    overflow-wrap: anywhere;
  }
  h3 {
    margin: 0 0 var(--ha-space-2, 8px);
    font-size: var(--ha-font-size-l, 16px);
  }
  .subtitle,
  .secondary {
    color: var(--secondary-text-color);
    font-size: var(--ha-font-size-m, 14px);
    line-height: var(--ha-line-height-normal, 1.6);
  }
  .content {
    padding: var(--ha-space-1, 4px) var(--ha-space-5, 20px)
      var(--ha-space-5, 20px);
  }
  .state {
    padding: var(--ha-space-5, 20px) 0;
    display: flex;
    gap: var(--ha-space-3, 12px);
    align-items: center;
    line-height: var(--ha-line-height-normal, 1.6);
  }
  .state ha-icon {
    color: var(--secondary-text-color);
    flex-shrink: 0;
  }
  button {
    font: inherit;
    color: inherit;
    background: transparent;
    border: 0;
    cursor: pointer;
    min-height: 44px;
    border-radius: var(--ha-border-radius-md, 8px);
  }
  .icon-button {
    width: 44px;
    display: grid;
    place-items: center;
    flex-shrink: 0;
    color: var(--secondary-text-color);
  }
  button,
  summary {
    transition: background-color var(--ha-animation-duration-fast, 150ms) ease;
  }
  button:hover,
  summary:hover {
    background: var(
      --ha-color-fill-neutral-quiet-hover,
      var(--secondary-background-color)
    );
  }
  :is(
    button,
    summary,
    a,
    input,
    select,
    .share-text,
    #share-preview-heading
  ):focus-visible {
    outline: 2px solid var(--ha-color-focus, var(--primary-color));
    outline-offset: 2px;
  }
  ha-icon {
    width: 22px;
    height: 22px;
    display: inline-flex;
    vertical-align: middle;
  }
  .trip-timetable {
    display: inline-flex;
    align-items: center;
    min-height: 44px;
    color: var(--primary-color);
  }
  .share-toggle,
  .share-buttons button {
    min-width: 44px;
    padding-inline: 12px;
    border: 1px solid var(--divider-color);
  }
  .share-toggle {
    margin-top: 12px;
  }
  .share-preview {
    padding: 12px;
    margin-top: 12px;
    border: 1px solid var(--divider-color);
    border-radius: var(--ha-border-radius-md, 8px);
    overflow-wrap: anywhere;
  }
  .share-text {
    margin: 8px 0;
    padding: 8px;
    border-radius: var(--ha-border-radius-md, 8px);
    background: var(--secondary-background-color);
    font: inherit;
    white-space: pre-wrap;
    user-select: text;
  }
  .share-calendar dt {
    font-size: var(--ha-font-size-m, 14px);
    color: var(--secondary-text-color);
  }
  .share-calendar dd {
    margin: 0 0 8px;
  }
  .share-buttons {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
  .share-buttons button {
    max-width: 100%;
    overflow-wrap: anywhere;
  }
  .share-buttons button:disabled {
    opacity: 0.65;
    cursor: default;
  }
  .planner {
    border-top: 1px solid var(--divider-color);
    margin-top: 16px;
    padding-top: 16px;
    overflow-wrap: anywhere;
  }
  .planner form {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 9rem), 1fr));
    gap: 8px;
  }
  .alternative dl {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
  }
  .planner label {
    display: grid;
    gap: 4px;
    min-width: 0;
    color: var(--secondary-text-color);
    font-size: var(--ha-font-size-m, 14px);
  }
  .planner :is(input, select, button) {
    width: 100%;
    min-width: 0;
    min-height: 44px;
    padding-inline: 8px;
    border: 1px solid var(--divider-color);
    border-radius: var(--ha-border-radius-md, 8px);
    background: var(--secondary-background-color);
    color: var(--primary-text-color);
    font: inherit;
  }
  .planner button {
    align-self: end;
    border-color: var(--primary-color);
    font-weight: var(--ha-font-weight-medium, 500);
  }
  .planner button:disabled {
    opacity: 0.65;
    cursor: wait;
  }
  .planner-sort {
    margin-block: 8px;
  }
  .alternatives {
    display: grid;
    gap: 8px;
    padding: 0;
    margin: 8px 0;
    list-style: none;
  }
  .alternative {
    padding: 8px;
    border: 1px solid var(--divider-color);
    border-radius: var(--ha-border-radius-md, 8px);
  }
  .alternative dl {
    margin: 0;
  }
  .alternative dt {
    color: var(--secondary-text-color);
    font-size: var(--ha-font-size-m, 14px);
  }
  .alternative dd {
    margin: 0;
  }
  .timing {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
    gap: var(--ha-space-3, 12px);
    align-items: center;
    margin: var(--ha-space-3, 12px) 0 var(--ha-space-4, 16px);
  }
  .timing .time {
    font-size: clamp(1.5rem, 7cqi, 2.25rem);
    font-weight: var(--ha-font-weight-bold, 700);
    letter-spacing: -0.025em;
    line-height: 1.3;
  }
  /* The arrow points from origin to destination in either reading direction. */
  :host(:dir(rtl)) .timing > ha-icon {
    transform: scaleX(-1);
  }
  .timing .destination {
    text-align: end;
  }
  .stop-name {
    font-weight: var(--ha-font-weight-medium, 500);
    margin-top: 6px;
    overflow-wrap: anywhere;
    line-height: 1.4;
  }
  .chip {
    display: inline-flex;
    gap: 6px;
    align-items: center;
    padding: 6px 10px;
    border-radius: var(--ha-border-radius-md, 8px);
    font-size: var(--ha-font-size-m, 14px);
    font-weight: var(--ha-font-weight-medium, 500);
    max-width: 100%;
    overflow-wrap: anywhere;
  }
  .chip ha-icon {
    flex-shrink: 0;
  }
  .status {
    display: flex;
    gap: var(--ha-space-2, 8px);
    align-items: center;
    margin: var(--ha-space-3, 12px) 0;
    font-size: var(--ha-font-size-m, 14px);
  }
  .active-vehicle {
    padding-block: var(--ha-space-2, 8px);
    border-top: 1px solid var(--divider-color);
    border-bottom: 1px solid var(--divider-color);
    font-size: var(--ha-font-size-m, 14px);
    overflow-wrap: anywhere;
  }
  .leg-marker {
    margin-inline-start: var(--ha-space-2, 8px);
  }
  .metrics {
    display: flex;
    flex-wrap: wrap;
    gap: var(--ha-space-2, 8px) var(--ha-space-4, 16px);
    margin: var(--ha-space-3, 12px) 0 var(--ha-space-4, 16px);
    color: var(--secondary-text-color);
    font-size: var(--ha-font-size-m, 14px);
  }
  .metric {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .alert-strip {
    display: flex;
    align-items: center;
    gap: var(--ha-space-2, 8px);
    padding: var(--ha-space-3, 12px);
    color: var(--ha-color-on-warning-normal, var(--primary-text-color));
    background: var(
      --ha-color-fill-warning-quiet-resting,
      color-mix(in srgb, var(--warning-color) 14%, var(--card-background-color))
    );
    border-radius: var(--ha-border-radius-lg, 12px);
    margin: var(--ha-space-3, 12px) 0;
    font-size: var(--ha-font-size-m, 14px);
    overflow-wrap: anywhere;
  }
  .alert-strip ha-icon {
    color: var(--warning-color);
  }
  .disclosure {
    width: 100%;
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-top: 1px solid var(--divider-color);
    border-radius: 0;
    padding: var(--ha-space-3, 12px) 0;
    text-align: start;
    margin-top: var(--ha-space-3, 12px);
  }
  .legs,
  .departures,
  .alerts,
  .calling-stops {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .leg {
    border-inline-start: 3px solid var(--primary-color);
    padding: var(--ha-space-1, 4px) 0 var(--ha-space-3, 12px)
      var(--ha-space-4, 16px);
    margin: var(--ha-space-2, 8px) 0 0 var(--ha-space-1, 4px);
  }
  .endpoint,
  .call {
    display: flex;
    justify-content: space-between;
    gap: var(--ha-space-4, 16px);
    align-items: baseline;
    margin: 10px 0;
  }
  .endpoint > div,
  .call > div {
    min-width: 0;
    overflow-wrap: anywhere;
  }
  .endpoint time,
  .call time {
    flex-shrink: 0;
    font-variant-numeric: tabular-nums;
  }
  .endpoint .label {
    font-weight: var(--ha-font-weight-medium, 500);
  }
  .call {
    position: relative;
    padding-inline-start: var(--ha-space-3, 12px);
    font-size: var(--ha-font-size-m, 14px);
  }
  .call::before {
    content: "";
    position: absolute;
    inset-inline-start: -5px;
    top: 6px;
    width: 9px;
    height: 9px;
    border: 2px solid var(--primary-color);
    border-radius: var(--ha-border-radius-circle, 50%);
    background: var(--card-background-color);
  }
  .calling-stops {
    border-inline-start: 2px solid var(--primary-color);
    margin-inline-start: var(--ha-space-1, 4px);
  }
  .call .prediction {
    color: var(--secondary-text-color);
    display: block;
    font-size: var(--ha-font-size-s, 12px);
  }
  details {
    margin-top: var(--ha-space-3, 12px);
  }
  summary {
    cursor: pointer;
    min-height: 44px;
    padding: var(--ha-space-3, 12px) var(--ha-space-1, 4px);
    border-radius: var(--ha-border-radius-md, 8px);
    font-size: var(--ha-font-size-m, 14px);
  }
  .board-views,
  .board-filters {
    gap: var(--ha-space-2, 8px);
    margin-block-end: var(--ha-space-3, 12px);
  }
  .board-views {
    display: flex;
    flex-wrap: wrap;
  }
  .board-views button,
  .clear-board-filters,
  .board-filters select {
    min-inline-size: 44px;
    min-block-size: 44px;
    padding-inline: var(--ha-space-2, 8px);
    border: 1px solid var(--divider-color);
    border-radius: var(--ha-border-radius-md, 8px);
  }
  .board-views button[aria-pressed="true"] {
    border-color: var(--primary-color);
    background: var(
      --ha-color-fill-primary-quiet-resting,
      var(--secondary-background-color)
    );
    font-weight: var(--ha-font-weight-bold, 700);
  }
  .board-filters {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 7rem), 1fr));
  }
  .board-filters label {
    display: grid;
    gap: var(--ha-space-1, 4px);
    min-inline-size: 0;
    color: var(--secondary-text-color);
    font-size: var(--ha-font-size-m, 14px);
  }
  .board-filters select {
    inline-size: 100%;
    background: var(--secondary-background-color);
    color: var(--primary-text-color);
    font: inherit;
  }
  .departure {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 10px;
    padding: var(--ha-space-4, 16px) 0;
    border-bottom: 1px solid var(--divider-color);
  }
  .departure:last-child,
  .alert:last-child {
    border-bottom: 0;
  }
  .departure .destination-name {
    margin-top: var(--ha-space-2, 8px);
  }
  .departure > div:first-child {
    overflow-wrap: anywhere;
  }
  .departure-status {
    display: flex;
    flex-wrap: wrap;
    gap: var(--ha-space-1, 4px);
    margin-top: var(--ha-space-1, 4px);
  }
  .departure-status span {
    padding: var(--ha-space-1, 4px) var(--ha-space-2, 8px);
    background: var(
      --ha-color-fill-neutral-quiet-resting,
      var(--secondary-background-color)
    );
    border-radius: var(--ha-border-radius-md, 8px);
    font-size: var(--ha-font-size-s, 12px);
  }
  .expected-time {
    margin-top: var(--ha-space-2, 8px);
  }
  .departure .when {
    text-align: end;
    white-space: nowrap;
    font-size: var(--ha-font-size-l, 16px);
    font-weight: var(--ha-font-weight-bold, 700);
    font-variant-numeric: tabular-nums;
  }
  .departure .when .secondary {
    font-weight: var(--ha-font-weight-normal, 400);
    margin-top: var(--ha-space-1, 4px);
  }
  .alert {
    padding: var(--ha-space-4, 16px) 0;
    border-bottom: 1px solid var(--divider-color);
  }
  .alert-title {
    display: flex;
    align-items: flex-start;
    gap: 10px;
  }
  .alert-title ha-icon {
    color: var(--warning-color);
    flex-shrink: 0;
  }
  .description {
    white-space: pre-line;
    overflow-wrap: anywhere;
    line-height: var(--ha-line-height-normal, 1.6);
    font-size: var(--ha-font-size-m, 14px);
  }
  .note {
    margin-top: var(--ha-space-3, 12px);
    color: var(--secondary-text-color);
    font-size: var(--ha-font-size-s, 12px);
    line-height: var(--ha-line-height-normal, 1.6);
  }
  @container (max-width: 340px) {
    header {
      padding: var(--ha-space-4, 16px) var(--ha-space-4, 16px)
        var(--ha-space-2, 8px);
      gap: var(--ha-space-2, 8px);
    }
    .content {
      padding: var(--ha-space-1, 4px) var(--ha-space-4, 16px)
        var(--ha-space-4, 16px);
    }
    .timing {
      gap: 6px;
    }
    .endpoint,
    .call {
      gap: var(--ha-space-2, 8px);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    *,
    *::before {
      animation: none !important;
      transition: none !important;
    }
  }
`;
